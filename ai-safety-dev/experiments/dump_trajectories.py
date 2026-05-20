#!/usr/bin/env python3
"""Dump zone trajectories for all authored-calendar rerun results.

Reads results/<persona>_authored_rerun.json (the per-row Stage-4 output) and
emits a flat CSV keyed by (persona, day). Used by the Stage-4 rule-change
protocol as the baseline snapshot before/after a rule edit.

Output columns:
  persona, day, expected, predicted, match, n_triggers, triggered_rules

triggered_rules is pipe-delimited so the column survives CSV parsing.
"""
import csv
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent


def main() -> None:
    out = csv.writer(sys.stdout)
    out.writerow(["persona", "day", "expected", "predicted", "match",
                  "n_triggers", "triggered_rules"])
    paths = sorted((HERE / "results").glob("*_authored_rerun.json"))
    if not paths:
        sys.stderr.write("no *_authored_rerun.json files in results/\n")
        sys.exit(1)
    for p in paths:
        data = json.loads(p.read_text(encoding="utf-8"))
        persona = data.get("persona") or p.stem.split("_")[0]
        for r in data["rows"]:
            rules = r.get("triggered_rules", []) or []
            out.writerow([persona, r["day"], r["expected"], r["predicted"],
                          r["match"], len(rules), " | ".join(rules)])


if __name__ == "__main__":
    main()
