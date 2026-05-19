#!/usr/bin/env python3
"""Post-hoc: evaluate the un-optimised vs MIPRO-compiled Stage-3 program on
train / dev / test, to tell overfit (train up, test flat) from no-op (flat
everywhere). Reuses dspy_stage3.py wiring; needs model calls (RouterAI)."""
import argparse, json, os

import dspy
from dspy.evaluate import Evaluate

from dspy_stage3 import HERE, ScoreBehaviour, make_splits, zone_metric


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", default="openai/deepseek/deepseek-v3.2")
    ap.add_argument("--api-base", default="https://routerai.ru/api/v1")
    ap.add_argument("--api-key", default=os.environ.get("ROUTERAI_API_KEY"))
    args = ap.parse_args()

    dspy.configure(lm=dspy.LM(model=args.model, api_base=args.api_base,
                              api_key=args.api_key, temperature=0.0, max_tokens=2000))

    splits = make_splits()
    baseline = dspy.ChainOfThought(ScoreBehaviour)
    compiled = dspy.ChainOfThought(ScoreBehaviour)
    compiled.load(str(HERE / "results" / "dspy_stage3_program.json"))

    rows = {}
    for name in ("train", "dev", "test"):
        ev = Evaluate(devset=splits[name], metric=zone_metric,
                      num_threads=4, display_progress=True)
        b = getattr(ev(baseline), "score", None)
        o = getattr(ev(compiled), "score", None)
        rows[name] = {"n": len(splits[name]), "baseline": b, "compiled": o,
                      "delta": round(o - b, 2)}
        print(f"{name:5s} (n={rows[name]['n']:3d}): baseline {b:.1f}  "
              f"compiled {o:.1f}  delta {o - b:+.1f}")

    (HERE / "results" / "dspy_stage3_split_eval.json").write_text(
        json.dumps({"model": args.model, "splits": rows}, indent=2))
    print("wrote results/dspy_stage3_split_eval.json")


if __name__ == "__main__":
    main()
