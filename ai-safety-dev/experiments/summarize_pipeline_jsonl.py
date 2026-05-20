"""Rebuild a pipeline summary.json from any (possibly partial) pipeline jsonl.

Safety net for `mindguard_pipeline.py`: the per-row jsonl is flushed
incrementally and always recoverable, but the summary is written only once
at completion (or when SIGINT is caught). A SIGKILL or crash loses the
summary even though the data on disk is fine.

This tool reads any pipeline_*.jsonl and rebuilds the matching summary
post-hoc. The output summary carries `partial: true` if it cannot find a
sibling `*.summary.json` (i.e. the run never produced one — most likely
SIGKILLed).

Usage:
    python summarize_pipeline_jsonl.py path/to/pipeline_*.jsonl
    python summarize_pipeline_jsonl.py --all results/mindguard/
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import Counter
from pathlib import Path


def summarize_jsonl(jsonl_path: Path) -> dict:
    rows = []
    bad = 0
    for line in jsonl_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            bad += 1
    rows.sort(key=lambda r: r.get("conv_id", -1))
    zones = [r.get("predicted_zone") for r in rows if "predicted_zone" in r]
    zc = Counter(zones)
    triggers = Counter()
    for r in rows:
        for t in r.get("triggered_rules", []):
            triggers[t] += 1

    name = jsonl_path.name
    sibling = jsonl_path.with_name(name.removesuffix(".jsonl") + ".summary.json")
    has_sibling = sibling.exists()

    return {
        "source_jsonl": str(jsonl_path),
        "had_finalised_summary": has_sibling,
        "partial": not has_sibling,
        "n_rows": len(rows),
        "n_unparseable_lines": bad,
        "n_scored": len(zones),
        "n_errors": len(rows) - len(zones),
        "zone_counts": dict(zc),
        "specificity_rate_green": round(zc["GREEN"] / len(zones), 4) if zones else None,
        "top_triggers": triggers.most_common(20),
    }


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("path", type=Path,
                   help="Either a single .jsonl file, or a directory if --all")
    p.add_argument("--all", action="store_true",
                   help="Treat path as a directory; summarise every pipeline_*.jsonl in it")
    p.add_argument("--write", action="store_true",
                   help="Write the rebuilt summary next to the jsonl as "
                        "<name>.summary.recovered.json")
    return p.parse_args()


def main() -> None:
    args = _parse_args()
    targets: list[Path]
    if args.all:
        if not args.path.is_dir():
            sys.exit(f"--all expects a directory: {args.path}")
        targets = sorted(args.path.glob("pipeline_*.jsonl"))
    else:
        targets = [args.path]

    for j in targets:
        s = summarize_jsonl(j)
        print(json.dumps(s, ensure_ascii=False, indent=2))
        if args.write:
            recovered = j.with_name(j.name.removesuffix(".jsonl") + ".summary.recovered.json")
            recovered.write_text(json.dumps(s, ensure_ascii=False, indent=2),
                                 encoding="utf-8")
            print(f"-> wrote {recovered}")


if __name__ == "__main__":
    main()
