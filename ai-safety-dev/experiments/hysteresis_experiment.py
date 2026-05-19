#!/usr/bin/env python3
"""Stage-4 hysteresis experiment (chapter-4, the escalation-timing failure).

The threshold recalibration (optimize_thresholds.py) fixed the YELLOW lower
edge but did nothing for escalation timing: the rule engine flips zone on a
single day, so escalation personas reach RED 4-7 days early and calm personas
pick up stray REDs. This adds *upward hysteresis* — a higher zone is only
reported after k consecutive raw trigger-days — and searches k offline.

Pure offline post-processing, like the threshold optimiser: no GPU, no model
calls. It runs *on top of* the optimised thresholds, so the result is the
consolidated pre-DSPy baseline (threshold-fix + hysteresis).

Hysteresis rule:
  - raw zone = the rule engine's verdict for the day;
  - a raw zone *higher* than the current reported zone is adopted only after
    k_red / k_yellow consecutive raw days at-or-above it;
  - a raw zone at-or-below the reported zone is adopted immediately
    (de-escalation is never delayed — the recovery persona must be able to drop).
"""
import json
from types import SimpleNamespace

from optimize_thresholds import (  # noqa: E402  (also runs the config-env shim)
    HERE, _run, compute_baselines, evaluate_risk_zone,
    load_rows, metrics, persona_class, split_personas,
)

RANK = {"GREEN": 0, "YELLOW": 1, "RED": 2}
K_RED_GRID = (1, 2, 3)
K_YELLOW_GRID = (1, 2)


def replay_hyst(rows: list[dict], th: dict, gate: int, k_red: int, k_yellow: int) -> list[tuple[str, str]]:
    history: list[SimpleNamespace] = []
    pairs: list[tuple[str, str]] = []
    reported = "GREEN"
    streak_zone, streak_len = None, 0
    need = {"YELLOW": k_yellow, "RED": k_red}
    for r in rows:
        recent = list(reversed(history))[:7]
        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])
        raw, _ = _run(evaluate_risk_zone(
            r["temporal_metrics"], r["danger_class_agg"], r["behavioral_scores"],
            baselines=baselines, recent_history=recent, thresholds=th, yellow_gate=gate))
        if RANK[raw] > RANK[reported]:                 # candidate escalation
            if raw == streak_zone:
                streak_len += 1
            else:
                streak_zone, streak_len = raw, 1
            if streak_len >= need[raw]:
                reported = raw
        else:                                          # same or de-escalation
            reported = raw
            streak_zone, streak_len = None, 0
        pairs.append((r["expected_zone"], reported))
        history.append(SimpleNamespace(
            risk_zone=reported, danger_class_agg=r["danger_class_agg"],
            behavioral_scores=r["behavioral_scores"], temporal_metrics=r["temporal_metrics"]))
    return pairs


def evaluate(personas: list[str], by_persona: dict, th: dict, gate: int,
             k_red: int, k_yellow: int) -> dict:
    pairs: list[tuple[str, str]] = []
    for p in personas:
        pairs += replay_hyst(by_persona[p], th, gate, k_red, k_yellow)
    return metrics(pairs)


def first_red_day(rows: list[dict], zones: list[str]) -> int | None:
    return next((rows[i]["day"] for i, z in enumerate(zones) if z == "RED"), None)


def timing_table(by_persona: dict, th: dict, gate: int, k_red: int, k_yellow: int) -> list[dict]:
    """First-RED day, designed vs predicted, for escalation personas."""
    out = []
    for p, rows in sorted(by_persona.items()):
        if persona_class(rows) != "escalation":
            continue
        exp_red = first_red_day(rows, [r["expected_zone"] for r in rows])
        zones = [z for _, z in replay_hyst(rows, th, gate, k_red, k_yellow)]
        pred_red = first_red_day(rows, zones)
        err = None if (exp_red is None or pred_red is None) else pred_red - exp_red
        out.append({"persona": p, "expected_first_red": exp_red,
                    "predicted_first_red": pred_red, "error_days": err})
    return out


def _timing_mae(table: list[dict]) -> float:
    errs = [abs(r["error_days"]) for r in table if r["error_days"] is not None]
    return round(sum(errs) / len(errs), 2) if errs else float("nan")


def _fmt(m: dict) -> str:
    z = m["per_zone_f1"]
    return (f"zone_match={m['zone_match']:.3f}  macro_f1={m['macro_f1']:.3f}  "
            f"F1[G/Y/R]={z['GREEN']:.2f}/{z['YELLOW']:.2f}/{z['RED']:.2f}  "
            f"fpr_green={m['fpr_on_green']:.3f}")


def main() -> None:
    by_persona = load_rows()
    calib, holdout = split_personas(by_persona)
    opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
    th = opt["optimised_thresholds_full"]
    gate = opt["yellow_gate"]
    fpr_cap = opt["fpr_on_green_cap"]
    print(f"thresholds = optimised (gate={gate}); fpr_on_green cap = {fpr_cap}")
    print(f"calibration: {calib}\nholdout    : {holdout}\n")

    # baseline = optimised thresholds, no hysteresis (k_red=k_yellow=1)
    base_c = evaluate(calib, by_persona, th, gate, 1, 1)
    print(f"NO hysteresis (k_red=1, k_yellow=1)")
    print(f"  calibration: {_fmt(base_c)}  escalation-timing MAE="
          f"{_timing_mae(timing_table(by_persona, th, gate, 1, 1))}\n")

    grid = []
    for kr in K_RED_GRID:
        for ky in K_YELLOW_GRID:
            m = evaluate(calib, by_persona, th, gate, kr, ky)
            mae = _timing_mae(timing_table(by_persona, th, gate, kr, ky))
            grid.append({"k_red": kr, "k_yellow": ky, "metrics": m, "timing_mae": mae})
            print(f"  k_red={kr} k_yellow={ky}: {_fmt(m)}  timing_MAE={mae}")

    feasible = [g for g in grid if g["metrics"]["fpr_on_green"] <= fpr_cap]
    best = max(feasible or grid, key=lambda g: g["metrics"]["macro_f1"])
    kr, ky = best["k_red"], best["k_yellow"]
    print(f"\nBEST: k_red={kr}, k_yellow={ky}")

    hold_m = evaluate(holdout, by_persona, th, gate, kr, ky)
    all_m = evaluate(sorted(by_persona), by_persona, th, gate, kr, ky)
    print(f"  holdout            : {_fmt(hold_m)}")
    print(f"  consolidated all-16: {_fmt(all_m)}")

    print("\nEscalation-timing — designed vs predicted first-RED day:")
    t_base = timing_table(by_persona, th, gate, 1, 1)
    t_best = {r["persona"]: r for r in timing_table(by_persona, th, gate, kr, ky)}
    print(f"  {'persona':10s} {'designed':>8s} {'no-hyst':>8s} {'hyst':>8s}")
    for r in t_base:
        b = t_best[r["persona"]]
        print(f"  {r['persona']:10s} {str(r['expected_first_red']):>8s} "
              f"{str(r['predicted_first_red']):>8s} {str(b['predicted_first_red']):>8s}")
    print(f"  escalation-timing MAE: no-hyst={_timing_mae(t_base)}  "
          f"hyst={_timing_mae(list(t_best.values()))}")

    out = {
        "method": "upward hysteresis on top of optimised thresholds; offline JSONL replay",
        "thresholds": th, "yellow_gate": gate,
        "calibration_personas": calib, "holdout_personas": holdout,
        "grid": grid, "best": {"k_red": kr, "k_yellow": ky},
        "metrics": {
            "baseline_no_hysteresis_calibration": base_c,
            "best_holdout": hold_m,
            "consolidated_pre_dspy_all16": all_m,
        },
        "escalation_timing": {
            "no_hysteresis": t_base,
            "with_hysteresis": list(t_best.values()),
            "mae_no_hysteresis": _timing_mae(t_base),
            "mae_with_hysteresis": _timing_mae(list(t_best.values())),
        },
    }
    (HERE / "results" / "hysteresis_experiment.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=2))
    print("\nwrote results/hysteresis_experiment.json")


if __name__ == "__main__":
    main()
