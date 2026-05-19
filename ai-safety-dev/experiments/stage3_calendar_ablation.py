#!/usr/bin/env python3
"""E9 -- calendar on/off ablation. Scores Stage 3 run three ways under a fixed
model, metric and persona corpus, isolating Sonya's longitudinal-calendar
mechanism (the central claim of her design, currently untested cleanly).

Arms:
  off       -- calendar disabled (evaluate_corpus.py --no-calendar)
  thematic  -- calendar on, thematic fields only (pre-E9 _format_calendar)
  anchored  -- calendar on, score-anchored digest (post-E9 _format_calendar)

The 'thematic' arm is simply the clean Phase-0 baseline corpus: it was produced
before the E9 _format_calendar edit, so it already carries a thematic-only
calendar. Pass it with --thematic. This driver runs the 'off' and 'anchored'
arms (unless pre-run files are supplied) and scores all three.

Metrics: zone metrics via optimize_thresholds.metrics() over the eval file's
own (expected_zone, predicted_zone) pairs, plus per-persona score *stability* --
the mean per-dimension population std across a persona's days. The calendar is
meant to suppress day-to-day variance, so 'anchored' should show the lowest
mean score std with zone metrics no worse.
"""
import argparse
import glob
import json
import os
import statistics
import subprocess

from optimize_thresholds import HERE, metrics

CORPUS = HERE / "results" / "corpus"
BASE = ["--generator", "qwen36",
        "--classifier-model", "ollama_chat/gpt-oss-safeguard:latest",
        "--classifier-api-base", "http://localhost:11434",
        "--stage3-model", "ollama_chat/gpt-oss:latest",
        "--stage3-api-base", "http://localhost:11434",
        "--temperature", "0.0"]


def newest_eval() -> str:
    return max(glob.glob(str(CORPUS / "*_corpus_eval.jsonl")), key=os.path.getmtime)


def run_arm(extra: list[str]) -> str:
    """Run evaluate_corpus.py and return the path of the eval file it produced."""
    subprocess.run(["python3", "-u", "experiments/evaluate_corpus.py", *BASE, *extra],
                   check=True, cwd=str(HERE.parent))
    return newest_eval()


def _rows(path: str) -> list[dict]:
    return [json.loads(l) for l in open(path, encoding="utf-8") if l.strip()]


def stability(rows: list[dict]) -> dict:
    """Per-persona mean population-std of the behavioural dimensions across days."""
    by: dict[str, list[dict]] = {}
    for r in rows:
        by.setdefault(r["persona"], []).append(r["behavioral_scores"])
    out = {}
    for p, scores in by.items():
        if len(scores) < 2:
            out[p] = 0.0
            continue
        keys = scores[0].keys()
        stds = [statistics.pstdev([s.get(k, 0.0) for s in scores]) for k in keys]
        out[p] = round(sum(stds) / len(stds), 4)
    return out


def zone_score(rows: list[dict]) -> dict:
    pairs = [(r["expected_zone"], r["predicted_zone"]) for r in rows]
    m = metrics(pairs)
    return {"zone_match": m["zone_match"], "macro_f1": m["macro_f1"],
            "fpr_on_green": m["fpr_on_green"], "per_zone_f1": m["per_zone_f1"]}


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--off", help="path to a pre-run calendar-off eval file")
    ap.add_argument("--thematic", help="path to the thematic-calendar eval file "
                    "(the clean Phase-0 baseline corpus)")
    ap.add_argument("--anchored", help="path to a pre-run score-anchored eval file")
    args = ap.parse_args()

    arms = {}
    arms["off"] = args.off or run_arm(["--no-calendar"])
    arms["anchored"] = args.anchored or run_arm([])
    if args.thematic:
        arms["thematic"] = args.thematic

    report = {}
    for name in ("off", "thematic", "anchored"):
        if name not in arms:
            continue
        rows = _rows(arms[name])
        stab = stability(rows)
        report[name] = {
            "file": os.path.basename(arms[name]),
            "zones": zone_score(rows),
            "stability_mean": round(sum(stab.values()) / len(stab), 4) if stab else 0.0,
            "stability_by_persona": stab,
        }
        z = report[name]["zones"]
        print(f"{name:9s}: zone_match={z['zone_match']}  macro_f1={z['macro_f1']}  "
              f"fpr_green={z['fpr_on_green']}  mean_score_std={report[name]['stability_mean']}")

    (HERE / "results" / "stage3_calendar_ablation.json").write_text(
        json.dumps(report, indent=2))
    print("wrote results/stage3_calendar_ablation.json")


if __name__ == "__main__":
    main()
