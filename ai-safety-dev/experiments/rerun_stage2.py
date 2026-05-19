#!/usr/bin/env python3
"""E8b -- Stage-2-only re-run. Re-classifies every corpus day with the graded
prompt (MULTI_LABEL_POLICY_PROMPT_V2) or a swapped classifier model, then replays
the deterministic Stage-4 engine over the FROZEN Stage-1/3 outputs stored in the
clean baseline corpus. Everything except the Stage-2 classifier is held fixed,
so the macro-F1 / FPR delta vs the clean baseline isolates the classifier change.

Stage 1 (`temporal_metrics`) and Stage 3 (`behavioral_scores`) are read from the
corpus rows that optimize_thresholds.load_rows() exposes -- so BASELINE_FILES in
optimize_thresholds.py must already point at the clean Phase-0 corpus.
"""
import argparse
import asyncio
import json
import os
from types import SimpleNamespace

import evaluate_corpus as ec
from optimize_thresholds import (  # noqa: E402
    HERE, _run, evaluate_risk_zone, compute_baselines,
    load_rows, split_personas, metrics,
)
import prompts_stage2_v2

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH = _opt["optimised_thresholds_full"]
GATE = _opt["yellow_gate"]


async def rerun_persona(persona: str, rows: list[dict], cfg) -> list[tuple[str, str]]:
    """Re-run Stage 2 for one persona; replay Stage 4 over the frozen Stage-1/3.
    Mirrors optimize_thresholds.replay() but swaps danger for a fresh Stage-2."""
    corpus = ec.load_persona_corpus(cfg.corpus_dir, persona, cfg.generator)
    history: list[SimpleNamespace] = []
    pairs: list[tuple[str, str]] = []
    for r in sorted(rows, key=lambda x: x["day"]):
        day = r["day"]
        if day not in corpus:
            continue
        danger, _n, _raw = await ec.stage2_danger(corpus[day], cfg)
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


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--classifier-model", default="ollama_chat/gpt-oss-safeguard:latest")
    ap.add_argument("--classifier-api-base", default="http://localhost:11434")
    ap.add_argument("--classifier-api-key", default=os.environ.get("ROUTERAI_API_KEY"))
    ap.add_argument("--generator", default="qwen36")
    ap.add_argument("--prompt", choices=["v1", "v2"], default="v2",
                    help="v2 = graded MULTI_LABEL_POLICY_PROMPT_V2 (default)")
    ap.add_argument("--only", nargs="*", default=None,
                    help="restrict to these personas (smoke runs)")
    args = ap.parse_args()

    # _classify_session reads the module global ec.MULTI_LABEL_POLICY_PROMPT at
    # call time, so reassigning it here swaps the policy for the whole run.
    if args.prompt == "v2":
        ec.MULTI_LABEL_POLICY_PROMPT = prompts_stage2_v2.MULTI_LABEL_POLICY_PROMPT_V2

    cfg = ec.RunConfig(
        corpus_dir=ec.DEFAULT_CORPUS,
        generator=args.generator,
        classifier_model=args.classifier_model,
        classifier_api_base=args.classifier_api_base,
        classifier_api_key=args.classifier_api_key,
        stage3_model="", stage3_api_base="", stage3_api_key=None,
        temperature=0.0, limit_days=None,
    )

    by_persona = load_rows()
    calib, holdout = split_personas(by_persona)
    if args.only:
        keep = set(args.only)
        calib = [p for p in calib if p in keep]
        holdout = [p for p in holdout if p in keep]

    out: dict = {"classifier_model": args.classifier_model,
                 "prompt": f"MULTI_LABEL_POLICY_PROMPT_{args.prompt.upper()}",
                 "splits": {}}
    for split, personas in (("calib", calib), ("holdout", holdout)):
        pairs: list[tuple[str, str]] = []
        for p in personas:
            pairs += asyncio.run(rerun_persona(p, by_persona[p], cfg))
        m = metrics(pairs) if pairs else {}
        out["splits"][split] = m
        if pairs:
            print(f"{split:8s}: macro_f1={m['macro_f1']:.3f}  "
                  f"fpr_green={m['fpr_on_green']:.3f}  "
                  f"zone_match={m['zone_match']:.3f}  n={len(pairs)}")

    (HERE / "results" / "stage2_v2_rerun.json").write_text(json.dumps(out, indent=2))
    print("wrote results/stage2_v2_rerun.json")


if __name__ == "__main__":
    main()
