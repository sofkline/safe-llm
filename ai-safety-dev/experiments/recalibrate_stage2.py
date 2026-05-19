#!/usr/bin/env python3
"""E8a -- Stage-2 replay recalibration. Re-derive per-class flag labels from the
stored per-session confidences with grid-searched confidence cutoffs, re-aggregate
the danger signal, replay the deterministic Stage-4 engine, and pick the cutoff
that raises macro-F1 without raising the GREEN false-positive rate. NO model calls.

Builds directly on optimize_thresholds.py: same persona split (seed 42), the same
Stage-4 replay path (`evaluate_risk_zone` with the optimised thresholds + gate),
and the same `metrics()`. The only thing this script changes is how the per-class
danger labels are derived from the raw classifier confidences.

Requires corpus rows carrying `danger_predicts_raw` (added to evaluate_corpus.py
in Phase 0); rows without it fall back to their stored `danger_class_agg`.
"""
import json
from types import SimpleNamespace

from optimize_thresholds import (  # noqa: E402  (runs the config-env shim + sys.path)
    HERE, _run, evaluate_risk_zone, compute_baselines,
    load_rows, split_personas, metrics,
)
from behavioral.danger_agg import DANGER_CLASSES, _aggregate_predictions

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH = _opt["optimised_thresholds_full"]
GATE = _opt["yellow_gate"]
TAU_GRID = [0.3, 0.5, 0.7, 0.9]  # per-class confidence cutoffs to try


def reaggregate(raw_predicts: list[dict], taus: dict) -> dict:
    """Re-derive labels from confidence with per-class cutoffs, then aggregate."""
    relabelled = []
    for pred in raw_predicts:
        out = {}
        for cls in DANGER_CLASSES:
            entry = pred.get(cls)
            if entry and isinstance(entry, dict):
                conf = float(entry.get("confidence", 0.0))
                out[cls] = {"confidence": conf,
                            "label": 1 if conf >= taus[cls] else 0}
        relabelled.append(out)
    return _aggregate_predictions(relabelled)


def replay_recalibrated(rows: list[dict], taus: dict | None) -> list[tuple[str, str]]:
    """Stage-4 replay over one persona's rows. Mirrors optimize_thresholds.replay()
    but swaps `danger_class_agg` for a confidence-recalibrated re-aggregation.
    `taus=None` -> use the stored danger unchanged (the baseline arm)."""
    history: list[SimpleNamespace] = []
    pairs: list[tuple[str, str]] = []
    for r in rows:
        raw = r.get("danger_predicts_raw")
        danger = reaggregate(raw, taus) if (taus is not None and raw) else r["danger_class_agg"]
        recent = list(reversed(history))[:7]
        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])
        zone, _ = _run(evaluate_risk_zone(
            r["temporal_metrics"], danger, r["behavioral_scores"],
            baselines=baselines, recent_history=recent,
            thresholds=OPT_TH, yellow_gate=GATE))
        pairs.append((r["expected_zone"], zone))
        history.append(SimpleNamespace(
            risk_zone=zone, danger_class_agg=danger,
            behavioral_scores=r["behavioral_scores"],
            temporal_metrics=r["temporal_metrics"]))
    return pairs


def score(by_persona: dict, personas: list[str], taus: dict | None) -> dict:
    pairs: list[tuple[str, str]] = []
    for p in personas:
        pairs += replay_recalibrated(by_persona[p], taus)
    return metrics(pairs)


def main() -> None:
    by_persona = load_rows()
    calib, holdout = split_personas(by_persona)

    have_raw = sum(1 for p in by_persona for r in by_persona[p]
                   if r.get("danger_predicts_raw"))
    total = sum(len(v) for v in by_persona.values())
    print(f"corpus: {total} day-points, {have_raw} carry raw predicts")
    if have_raw == 0:
        raise SystemExit("no rows carry danger_predicts_raw -- run a Phase-0 "
                         "corpus first (evaluate_corpus.py persists it)")

    # baseline: classifier's own labels, untouched
    base = score(by_persona, calib, None)
    print(f"baseline (calib): macro_f1={base['macro_f1']:.3f}  "
          f"fpr_green={base['fpr_on_green']:.3f}  zone_match={base['zone_match']:.3f}")

    best = None  # (tau, calib_metrics)
    for tau in TAU_GRID:
        taus = {c: tau for c in DANGER_CLASSES}
        m = score(by_persona, calib, taus)
        print(f"  tau={tau}: macro_f1={m['macro_f1']:.3f}  "
              f"fpr_green={m['fpr_on_green']:.3f}  zone_match={m['zone_match']:.3f}")
        # objective: maximise macro-F1 subject to not raising FPR-on-GREEN
        if m["fpr_on_green"] <= base["fpr_on_green"] + 1e-9:
            if best is None or m["macro_f1"] > best[1]["macro_f1"]:
                best = (tau, m)

    out: dict = {
        "baseline": base,
        "tau_grid": TAU_GRID,
        "optimised_thresholds": OPT_TH,
        "yellow_gate": GATE,
    }
    if best is None:
        print("\nNO tau beats baseline at equal-or-lower FPR-on-GREEN -- the "
              "over-confidence fault is entangled with the labels, not the "
              "confidence cutoff. Reportable negative result.")
        out["result"] = "no_improvement"
    else:
        tau, cm = best
        hm = score(by_persona, holdout, {c: tau for c in DANGER_CLASSES})
        gap = cm["macro_f1"] - hm["macro_f1"]
        print(f"\nBEST tau={tau}: calib macro_f1={cm['macro_f1']:.3f}  "
              f"holdout macro_f1={hm['macro_f1']:.3f}  gap={gap:+.3f}")
        out["result"] = "improved"
        out["best_tau"] = tau
        out["calibration"] = cm
        out["holdout"] = hm
        out["calib_holdout_gap"] = round(gap, 4)

    (HERE / "results" / "stage2_recalibration.json").write_text(
        json.dumps(out, indent=2))
    print("wrote results/stage2_recalibration.json")


if __name__ == "__main__":
    main()
