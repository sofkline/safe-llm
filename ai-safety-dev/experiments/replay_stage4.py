#!/usr/bin/env python3
"""Offline replay of Stage-2 aggregation + Stage-4 rule engine on stored
per-persona corpus_eval.jsonl files.

The engineering changes that motivated this script all live in the
*deterministic* part of the pipeline:

- src/behavioral/danger_agg.py::_aggregate_predictions: drops malformed
  all-zero-confidence Stage-2 predictions.
- src/behavioral/risk_engine.py::_check_yellow_triggers: adds the
  sustained-delegation single-strong-signal YELLOW rule.
- src/behavioral/risk_engine.py::evaluate_risk_zone: converts
  sustained_yellow >= 3 days from RED escalator to YELLOW reinforcement.

None of them touch the LLM-side components (Stage-2 classifier, Stage-3
behavioral LLM, Stage-1 temporal metrics). Therefore the existing
`danger_predicts_raw`, `behavioral_scores`, and `temporal_metrics` fields
saved by `evaluate_corpus.py` are sufficient to replay the post-LLM
pipeline without paying token cost.

Pattern mirrors `optimize_thresholds.py` / `hysteresis_experiment.py` —
deterministic post-processing of stored per-day rows.

Usage:
    python3 experiments/replay_stage4.py --jsonl <path>
    python3 experiments/replay_stage4.py --jsonl <path> --persona dmitry

Outputs zone-match before/after for the chosen persona(s) and writes a
sibling `*.replayed.jsonl` with the new predicted_zone / triggered_rules
columns.
"""
from __future__ import annotations
import argparse
import asyncio
import importlib.util
import json
import sys
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src" / "behavioral"

# `behavioral.danger_agg` has top-level `database` imports that require many
# environment vars. We need only the pure-dict helpers, so inline them here
# rather than booting the whole settings stack. Keep in sync with the
# original module — both `_is_degenerate_prediction` and
# `_aggregate_predictions` are exact copies as of 2026-05-20.

DANGER_CLASSES = ["suicide", "psychosis", "depression", "obsession", "anthropomorphism"]


def _is_degenerate_prediction(pred: dict) -> bool:
    total_conf = 0.0
    for cls in DANGER_CLASSES:
        entry = pred.get(cls)
        if entry and isinstance(entry, dict):
            total_conf += entry.get("confidence", 0.0)
    return total_conf == 0.0


def _empty_danger_agg() -> dict:
    return {
        "suicide_avg": 0.0, "suicide_max": 0.0, "suicide_flag_rate": 0.0,
        "psychosis_avg": 0.0, "psychosis_max": 0.0, "psychosis_flag_rate": 0.0,
        "depression_avg": 0.0, "depression_flag_rate": 0.0,
        "obsession_avg": 0.0, "anthropomorphism_avg": 0.0, "max_class_avg": 0.0,
    }


def _aggregate_predictions(predictions: list[dict]) -> dict:
    if not predictions:
        return _empty_danger_agg()
    predictions = [p for p in predictions if not _is_degenerate_prediction(p)]
    if not predictions:
        return _empty_danger_agg()

    class_confidences: dict[str, list[float]] = {c: [] for c in DANGER_CLASSES}
    class_flags: dict[str, list[int]] = {c: [] for c in DANGER_CLASSES}
    for pred in predictions:
        for cls in DANGER_CLASSES:
            entry = pred.get(cls)
            if entry and isinstance(entry, dict):
                conf = entry.get("confidence", 0.0)
                label = entry.get("label", 0)
                danger = conf if label == 1 else 0.0
                class_confidences[cls].append(danger)
                class_flags[cls].append(label)
    avgs = {c: (sum(confs) / len(confs) if confs else 0.0)
            for c, confs in class_confidences.items()}
    return {
        "suicide_avg": round(avgs["suicide"], 4),
        "suicide_max": round(max(class_confidences["suicide"], default=0.0), 4),
        "suicide_flag_rate": round(
            sum(class_flags["suicide"]) / len(class_flags["suicide"])
            if class_flags["suicide"] else 0.0, 4),
        "psychosis_avg": round(avgs["psychosis"], 4),
        "psychosis_max": round(max(class_confidences["psychosis"], default=0.0), 4),
        "psychosis_flag_rate": round(
            sum(class_flags["psychosis"]) / len(class_flags["psychosis"])
            if class_flags["psychosis"] else 0.0, 4),
        "depression_avg": round(avgs["depression"], 4),
        "depression_flag_rate": round(
            sum(class_flags["depression"]) / len(class_flags["depression"])
            if class_flags["depression"] else 0.0, 4),
        "obsession_avg": round(avgs["obsession"], 4),
        "anthropomorphism_avg": round(avgs["anthropomorphism"], 4),
        "max_class_avg": round(max(avgs.values()), 4),
    }


# risk_engine.py has no problematic imports — load it via importlib.
def _load_risk_engine():
    spec = importlib.util.spec_from_file_location("_replay_risk_engine", SRC / "risk_engine.py")
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["_replay_risk_engine"] = mod
    spec.loader.exec_module(mod)
    return mod

evaluate_risk_zone = _load_risk_engine().evaluate_risk_zone


def compute_baselines(history: list[dict]) -> dict:
    """Inlined from src/behavioral/temporal.py::compute_baselines for replay."""
    if not history:
        return {
            "avg_daily_messages": 0, "avg_night_messages": 0,
            "avg_active_hours": 0, "avg_prompt_length": 0,
            "avg_inter_message_interval": 0,
        }
    n = len(history)
    return {
        "avg_daily_messages": sum(h.get("daily_message_count", 0) for h in history) / n,
        "avg_night_messages": sum(h.get("night_messages", 0) for h in history) / n,
        "avg_active_hours": sum(h.get("daily_active_hours", 0) for h in history) / n,
        "avg_prompt_length": sum(h.get("avg_prompt_length_chars", 0) for h in history) / n,
        "avg_inter_message_interval": sum(h.get("avg_inter_message_interval_min", 0) for h in history) / n,
    }


async def replay_persona(rows: list[dict]) -> dict:
    """Replay Stage-2 agg + Stage-4 over a persona's stored per-day rows.

    `rows` is the list of corpus_eval rows for one persona, day-sorted.
    """
    rows = sorted(rows, key=lambda r: r["day"])
    new_rows: list[dict] = []
    history: list[SimpleNamespace] = []  # newest appended last (same as evaluate_corpus)
    n_match_before = 0
    n_match_after = 0

    for r in rows:
        raw_predicts = r.get("danger_predicts_raw") or []
        danger_new = _aggregate_predictions(raw_predicts)  # filtered re-aggregation

        # Baselines computed from last-7-days temporal_metrics so the
        # baseline-dependent rules (interval_shrinking, high-message-volume
        # trending) replay correctly.
        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])
        recent = list(reversed(history))[:7]
        zone, triggers = await evaluate_risk_zone(
            r["temporal_metrics"],
            danger_new,
            r["behavioral_scores"],
            baselines=baselines,
            recent_history=recent,
            context={"persona": r["persona"], "day": r["day"]},
        )
        # Track both old and new match.
        if r.get("match"):
            n_match_before += 1
        if zone == r["expected_zone"]:
            n_match_after += 1
        new_rows.append({
            **r,
            "predicted_zone_old": r["predicted_zone"],
            "predicted_zone": zone,
            "triggered_rules_old": r.get("triggered_rules", []),
            "triggered_rules": triggers,
            "danger_class_agg_old": r.get("danger_class_agg", {}),
            "danger_class_agg": danger_new,
            "match_old": r.get("match"),
            "match": zone == r["expected_zone"],
        })
        history.append(SimpleNamespace(
            risk_zone=zone, danger_class_agg=danger_new,
            behavioral_scores=r["behavioral_scores"],
            temporal_metrics=r["temporal_metrics"],
        ))
    return {
        "rows": new_rows,
        "n_match_before": n_match_before,
        "n_match_after": n_match_after,
        "n_total": len(rows),
    }


async def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--jsonl", required=True,
                    help="path to a corpus_eval.jsonl file")
    ap.add_argument("--persona", default=None,
                    help="filter to one persona (default: all in the file)")
    ap.add_argument("--out", default=None,
                    help="output path (default: <jsonl>.replayed.jsonl)")
    args = ap.parse_args()

    in_path = Path(args.jsonl)
    out_path = Path(args.out) if args.out else in_path.with_suffix(".replayed.jsonl")

    rows = [json.loads(l) for l in in_path.read_text(encoding="utf-8").splitlines() if l.strip()]
    if args.persona:
        rows = [r for r in rows if r["persona"] == args.persona]

    by_persona: dict[str, list[dict]] = {}
    for r in rows:
        by_persona.setdefault(r["persona"], []).append(r)

    all_new: list[dict] = []
    print(f"{'persona':<10s} {'before':>10s} {'after':>10s}  delta")
    for persona, prows in by_persona.items():
        res = await replay_persona(prows)
        all_new.extend(res["rows"])
        before = f"{res['n_match_before']}/{res['n_total']}"
        after = f"{res['n_match_after']}/{res['n_total']}"
        delta = res["n_match_after"] - res["n_match_before"]
        sign = "+" if delta > 0 else ""
        print(f"{persona:<10s} {before:>10s} {after:>10s}  {sign}{delta}")

    out_path.write_text("\n".join(json.dumps(r, ensure_ascii=False) for r in all_new) + "\n",
                        encoding="utf-8")
    print(f"\nwrote {out_path}")


if __name__ == "__main__":
    asyncio.run(main())
