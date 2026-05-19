#!/usr/bin/env python3
"""Three Stage-4 replay spikes attacking YELLOW-band collapse / Stage-3 noise.

All zero-cost: pure offline replay over existing corpus data, no model calls.

Spike 1 -- sticky (asymmetric) hysteresis. Current hysteresis delays *escalation*
  only; de-escalation is immediate, so a YELLOW persona with one noisy
  sub-threshold day collapses straight to GREEN. This requires k_down consecutive
  lower raw days before de-escalating. Targets the dominant YELLOW->GREEN error.

Spike 2 -- EWMA score smoothing. Smooth each persona's Stage-3 dimension series
  before Stage 4 -- a deterministic 'calendar' in the right channel (cf. E9,
  where the in-prompt calendar was null).

Spike 3 -- cross-model ensemble. Mean Stage-2 (re-aggregated from raw) and
  Stage-3 across deepseek-v3.2 + gpt-oss-120b, then replay. Decides whether
  per-model error is independent noise (ensembling lifts accuracy) or
  correlated/structural (it does not).

Hyperparameters (k_down, alpha) are grid-searched on the calibration split and
reported on holdout. Fixed reference = the consolidated baseline: optimised
thresholds + verified hysteresis (k_red=2, k_yellow=1, immediate de-escalation).
"""
import json
from types import SimpleNamespace

from optimize_thresholds import (  # noqa: E402  (also runs the config-env shim)
    HERE, CORPUS, _run, compute_baselines, evaluate_risk_zone,
    load_rows, metrics, split_personas,
)
from behavioral.danger_agg import _aggregate_predictions

RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH = _opt["optimised_thresholds_full"]
GATE = _opt["yellow_gate"]
_hyst = json.loads((HERE / "results" / "hysteresis_experiment.json").read_text())
K_RED = _hyst["best"]["k_red"]
K_YELLOW = _hyst["best"]["k_yellow"]

DEEPSEEK = "20260518_234328_corpus_eval.jsonl"
GPTOSS120B = "20260519_005707_corpus_eval.jsonl"


# ── replay with symmetric (sticky) hysteresis ────────────────────────────────

def replay_sticky(rows: list[dict], th: dict, gate: int,
                   k_red: int, k_yellow: int, k_down: int) -> list[tuple[str, str]]:
    """Stage-4 replay. Escalation needs k_yellow/k_red consecutive raw days;
    de-escalation needs k_down. k_down=1 reproduces immediate de-escalation."""
    history: list[SimpleNamespace] = []
    pairs: list[tuple[str, str]] = []
    reported = "GREEN"
    cand, streak = None, 0
    up_need = {"YELLOW": k_yellow, "RED": k_red}
    for r in rows:
        recent = list(reversed(history))[:7]
        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])
        raw, _ = _run(evaluate_risk_zone(
            r["temporal_metrics"], r["danger_class_agg"], r["behavioral_scores"],
            baselines=baselines, recent_history=recent, thresholds=th, yellow_gate=gate))
        if RANK[raw] == RANK[reported]:
            cand, streak = None, 0
        else:
            need = up_need[raw] if RANK[raw] > RANK[reported] else k_down
            if raw == cand:
                streak += 1
            else:
                cand, streak = raw, 1
            if streak >= need:
                reported = raw
                cand, streak = None, 0
        pairs.append((r["expected_zone"], reported))
        history.append(SimpleNamespace(
            risk_zone=reported, danger_class_agg=r["danger_class_agg"],
            behavioral_scores=r["behavioral_scores"], temporal_metrics=r["temporal_metrics"]))
    return pairs


def score(by_persona: dict, personas: list[str], k_down: int = 1,
          k_red: int = K_RED, k_yellow: int = K_YELLOW) -> dict:
    pairs: list[tuple[str, str]] = []
    for p in personas:
        pairs += replay_sticky(by_persona[p], OPT_TH, GATE, k_red, k_yellow, k_down)
    return metrics(pairs)


# ── EWMA smoothing of the Stage-3 score series ───────────────────────────────

def smooth_rows(rows: list[dict], alpha: float) -> list[dict]:
    """EWMA over behavioral_scores per dimension. alpha>=1.0 -> no smoothing."""
    if alpha >= 1.0:
        return rows
    out: list[dict] = []
    prev: dict | None = None
    for r in rows:
        bs = r["behavioral_scores"]
        if prev is None:
            sm = dict(bs)
        else:
            sm = {k: alpha * bs.get(k, 0.0) + (1 - alpha) * prev.get(k, 0.0) for k in bs}
        prev = sm
        nr = dict(r)
        nr["behavioral_scores"] = sm
        out.append(nr)
    return out


# ── cross-model ensemble ─────────────────────────────────────────────────────

def load_corpus(filename: str) -> dict[str, list[dict]]:
    by_persona: dict[str, list[dict]] = {}
    for line in (CORPUS / filename).read_text().splitlines():
        if line.strip():
            r = json.loads(line)
            by_persona.setdefault(r["persona"], []).append(r)
    for p in by_persona:
        by_persona[p].sort(key=lambda r: r["day"])
    return by_persona


def _danger_from_raw(r: dict) -> dict:
    """Re-aggregate danger from stored raw predicts with the (fixed) label gate."""
    raw = r.get("danger_predicts_raw")
    return _aggregate_predictions(raw) if raw else r["danger_class_agg"]


def ensemble(corpora: list[dict]) -> dict[str, list[dict]]:
    """Merge corpora by (persona, day): mean Stage-3 scores, mean re-aggregated
    danger metrics. Stage-1 metrics are deterministic -> taken from the first."""
    merged: dict[str, list[dict]] = {}
    base = corpora[0]
    for p, rows in base.items():
        out_rows = []
        for i, r in enumerate(rows):
            others = [c[p][i] for c in corpora]
            dims = r["behavioral_scores"].keys()
            bs = {k: sum(o["behavioral_scores"].get(k, 0.0) for o in others) / len(others)
                  for k in dims}
            dangers = [_danger_from_raw(o) for o in others]
            dkeys = dangers[0].keys()
            dg = {k: sum(d.get(k, 0.0) for d in dangers) / len(dangers) for k in dkeys}
            out_rows.append({**r, "behavioral_scores": bs, "danger_class_agg": dg})
        merged[p] = out_rows
    return merged


# ── driver ───────────────────────────────────────────────────────────────────

def _fmt(m: dict) -> str:
    return (f"zone_match={m['zone_match']:.3f}  macro_f1={m['macro_f1']:.3f}  "
            f"YELLOW_f1={m['per_zone_f1']['YELLOW']:.3f}  fpr_green={m['fpr_on_green']:.3f}")


def main() -> None:
    by_persona = load_rows()  # deepseek working corpus
    calib, holdout = split_personas(by_persona)
    report: dict = {}

    base_cal = score(by_persona, calib)
    base_hol = score(by_persona, holdout)
    report["baseline"] = {"calib": base_cal, "holdout": base_hol,
                          "params": {"k_red": K_RED, "k_yellow": K_YELLOW, "k_down": 1}}
    print(f"BASELINE (k_red={K_RED}, k_yellow={K_YELLOW}, k_down=1)")
    print(f"  calib  : {_fmt(base_cal)}")
    print(f"  holdout: {_fmt(base_hol)}")

    # Spike 1 -- sticky hysteresis: grid k_down on calib, report holdout
    print("\nSPIKE 1 -- sticky hysteresis (k_down grid)")
    s1 = []
    for kd in (1, 2, 3):
        m = score(by_persona, calib, k_down=kd)
        s1.append({"k_down": kd, "calib": m})
        print(f"  k_down={kd}: calib {_fmt(m)}")
    best1 = max(s1, key=lambda e: e["calib"]["macro_f1"])
    best1_hol = score(by_persona, holdout, k_down=best1["k_down"])
    best1["holdout"] = best1_hol
    print(f"  BEST k_down={best1['k_down']} -> holdout {_fmt(best1_hol)}")
    report["spike1_sticky_hysteresis"] = {"grid": s1, "best_k_down": best1["k_down"],
                                          "holdout": best1_hol}

    # Spike 2 -- EWMA smoothing: grid alpha on calib, report holdout
    print("\nSPIKE 2 -- EWMA score smoothing (alpha grid)")
    s2 = []
    for alpha in (1.0, 0.7, 0.5, 0.3):
        sm = {p: smooth_rows(by_persona[p], alpha) for p in by_persona}
        m = score(sm, calib)
        s2.append({"alpha": alpha, "calib": m})
        print(f"  alpha={alpha}: calib {_fmt(m)}")
    best2 = max(s2, key=lambda e: e["calib"]["macro_f1"])
    sm_best = {p: smooth_rows(by_persona[p], best2["alpha"]) for p in by_persona}
    best2_hol = score(sm_best, holdout)
    best2["holdout"] = best2_hol
    print(f"  BEST alpha={best2['alpha']} -> holdout {_fmt(best2_hol)}")
    report["spike2_ewma"] = {"grid": s2, "best_alpha": best2["alpha"],
                             "holdout": best2_hol}

    # Spike 3 -- cross-model ensemble (deepseek + gpt-oss-120b)
    print("\nSPIKE 3 -- cross-model ensemble (deepseek + gpt-oss-120b)")
    ds = load_corpus(DEEPSEEK)
    b120 = load_corpus(GPTOSS120B)
    common = sorted(set(ds) & set(b120))
    ens = ensemble([ds, b120])
    ens_cal = score(ens, [p for p in calib if p in common])
    ens_hol = score(ens, [p for p in holdout if p in common])
    print(f"  calib  : {_fmt(ens_cal)}")
    print(f"  holdout: {_fmt(ens_hol)}")
    report["spike3_ensemble"] = {"models": ["deepseek-v3.2", "gpt-oss-120b"],
                                 "calib": ens_cal, "holdout": ens_hol}

    out = HERE / "results" / "stage4_noise_spikes.json"
    out.write_text(json.dumps(report, indent=2))
    print(f"\nwrote {out.relative_to(HERE.parent)}")


if __name__ == "__main__":
    main()
