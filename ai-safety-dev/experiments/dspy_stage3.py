#!/usr/bin/env python3
"""DSPy optimisation of the Stage-3 behavioural-scoring prompt (chapter-4, E1).

Why Stage 3 (not the Stage-2 classifier): after the Stage-4 recalibration
(optimize_thresholds.py + hysteresis_experiment.py) the residual YELLOW failure
is localised to Stage 3 — the behavioural LLM emits near-binary, uncalibrated
scores, so 33/72 YELLOW day-points are under-scored into GREEN and a few are
over-scored into RED. This program optimises the Stage-3 prompt to emit a
*calibrated graded* 0.0-1.0 intensity.

Design
------
* Optimisable module: a DSPy program that maps a day's session text to the 7
  behavioural scores. DSPy (MIPROv2) rewrites the instruction and picks few-shot
  demos; Stages 1/2/4 stay as plain code.
* Metric: end-to-end, per day-point. DSPy's predicted scores are fed to the
  *recalibrated* Stage-4 engine; the resulting zone is compared to the persona's
  designed zone. Ordinal credit (exact 1.0 / adjacent 0.3 / opposite 0.0) so the
  GREEN<->RED collapse is punished hardest.
  NOTE: the metric runs Stage 4 with recent_history=[] — single-day rules only.
  Hysteresis is a trajectory-level post-process, applied at E7 eval, not here.
* Split: persona-level, frozen. Calibration personas -> train + dev (MIPRO
  validation); the 4 held-out personas -> test. DSPy never sees the test
  personas (calibration-vs-evaluation rule).

Run (needs model calls -> cloud / 192.168.87.25, NOT the local GPU):
    python dspy_stage3.py --smoke          # build trainset only, no model calls
    python dspy_stage3.py --model openai/<id> --api-base https://routerai.ru/api/v1
"""
import argparse
import json
import os
import random
from datetime import timedelta

from optimize_thresholds import (  # noqa: E402  (runs the config-env shim)
    HERE, _run, evaluate_risk_zone, load_rows, split_personas,
)
from evaluate_corpus import (  # noqa: E402
    ALL_PERSONAS, DEFAULT_CORPUS, EPOCH, build_stage3_sessions, load_persona_corpus,
)
from behavioral.behavioral_llm import _format_sessions_block, SCORE_KEYS  # noqa: E402

import dspy  # noqa: E402

GENERATOR = "qwen36"
ADJACENT = {("GREEN", "YELLOW"), ("YELLOW", "GREEN"), ("YELLOW", "RED"), ("RED", "YELLOW")}
SEED = 42

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH = _opt["optimised_thresholds_full"]
GATE = _opt["yellow_gate"]


# ── DSPy program ─────────────────────────────────────────────────────────────
class ScoreBehaviour(dspy.Signature):
    """Score one day of a user's messages to an AI assistant on seven
    behavioural-risk dimensions, each 0.0-1.0.

    Emit a CALIBRATED GRADED intensity, not a near-binary flag. Healthy,
    ordinary use is ~0.0-0.15. MODERATE distress — the user is struggling but
    not in crisis — must land in the MIDDLE of the range (~0.3-0.55); do not
    round it down to 0 or up to 0.8. Reserve 0.7-1.0 for severe, unambiguous
    signals. The seven dimensions: topic_concentration, decision_delegation,
    social_isolation, emotional_attachment, emotional_isolation, delusional,
    selfharm."""

    sessions_text: str = dspy.InputField(desc="today's user messages, grouped by session")
    calendar_text: str = dspy.InputField(desc="notable prior days; may be empty")
    scores: dict = dspy.OutputField(desc="JSON object with the 7 dimension keys, each a float 0.0-1.0")


def _coerce_scores(raw) -> dict | None:
    """Normalise the model output into the 7-key float dict, or None."""
    if isinstance(raw, str):
        try:
            raw = json.loads(raw)
        except (json.JSONDecodeError, TypeError):
            return None
    if not isinstance(raw, dict):
        return None
    out = {}
    for k in SCORE_KEYS:
        try:
            out[k] = max(0.0, min(1.0, float(raw.get(k, 0.0))))
        except (TypeError, ValueError):
            out[k] = 0.0
    return out


def zone_metric(example, pred, trace=None) -> float:
    """End-to-end ordinal zone match: DSPy scores -> recalibrated Stage 4."""
    scores = _coerce_scores(getattr(pred, "scores", None))
    if scores is None:
        return 0.0
    zone, _ = _run(evaluate_risk_zone(
        example.temporal, example.danger, scores,
        baselines={}, recent_history=[], thresholds=OPT_TH, yellow_gate=GATE))
    exp = example.expected_zone
    if zone == exp:
        return 1.0
    if (exp, zone) in ADJACENT:
        return 0.3
    return 0.0


# ── data ─────────────────────────────────────────────────────────────────────
def build_examples(personas: list[str], rows_by_persona: dict) -> list[dspy.Example]:
    examples: list[dspy.Example] = []
    for p in personas:
        rows = {r["day"]: r for r in rows_by_persona[p]}
        try:
            corpus = load_persona_corpus(DEFAULT_CORPUS, p, GENERATOR)
        except FileNotFoundError:
            print(f"  ! no corpus for {p}, skipped")
            continue
        cfg = ALL_PERSONAS[p]
        for day, row in sorted(rows.items()):
            if day not in corpus:
                continue
            sessions = build_stage3_sessions(day, corpus[day], cfg)
            today = EPOCH + timedelta(days=day - 1)
            ex = dspy.Example(
                sessions_text=_format_sessions_block(today, sessions),
                calendar_text="",
                temporal=row["temporal_metrics"], danger=row["danger_class_agg"],
                expected_zone=row["expected_zone"], persona=p, day=day,
            ).with_inputs("sessions_text", "calendar_text")
            examples.append(ex)
    return examples


def make_splits():
    """train + dev from calibration personas; test = the 4 held-out personas."""
    rows = load_rows()
    calib, holdout = split_personas(rows)
    rng = random.Random(SEED)
    shuffled = sorted(calib)
    rng.shuffle(shuffled)
    train_p, dev_p = shuffled[:8], shuffled[8:]
    return {
        "train": build_examples(train_p, rows),
        "dev": build_examples(dev_p, rows),
        "test": build_examples(holdout, rows),
        "personas": {"train": train_p, "dev": dev_p, "test": holdout},
    }


# ── main ─────────────────────────────────────────────────────────────────────
def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--smoke", action="store_true", help="build trainset only, no model calls")
    ap.add_argument("--model", default="openai/deepseek/deepseek-v3.2",
                    help="litellm model string for the Stage-3 LM "
                         "(openai/<id> routes through --api-base; RouterAI id "
                         "carries the vendor prefix, e.g. deepseek/deepseek-v3.2)")
    ap.add_argument("--api-base", default="https://routerai.ru/api/v1")
    ap.add_argument("--api-key", default=os.environ.get("ROUTERAI_API_KEY"))
    ap.add_argument("--auto", default="light", choices=["light", "medium", "heavy"])
    args = ap.parse_args()

    splits = make_splits()
    for name in ("train", "dev", "test"):
        print(f"{name:5s}: {len(splits[name]):3d} day-points  "
              f"personas={splits['personas'][name]}")

    if args.smoke:
        ex = splits["train"][0]
        print(f"\n--- example ({ex.persona} day {ex.day}, expected {ex.expected_zone}) ---")
        print(ex.sessions_text[:600])
        print("...\nsmoke ok — data wiring verified, no model calls made.")
        return

    # ---- real run: needs model calls (cloud / remote box) -------------------
    lm = dspy.LM(model=args.model, api_base=args.api_base or None,
                 api_key=args.api_key, temperature=0.0, max_tokens=2000)
    dspy.configure(lm=lm)

    program = dspy.ChainOfThought(ScoreBehaviour)

    from dspy.evaluate import Evaluate
    ev_test = Evaluate(devset=splits["test"], metric=zone_metric, num_threads=4, display_progress=True)
    base = ev_test(program)
    base = getattr(base, "score", base)   # dspy>=2.5 returns EvaluationResult
    print(f"\nbaseline (un-optimised) test score: {base}")

    # MIPROv2 API can shift between dspy minor versions — adjust if 3.1.3 differs.
    from dspy.teleprompt import MIPROv2
    tp = MIPROv2(metric=zone_metric, auto=args.auto)
    compiled = tp.compile(program, trainset=splits["train"], valset=splits["dev"],
                          requires_permission_to_run=False)

    opt = ev_test(compiled)
    opt = getattr(opt, "score", opt)
    print(f"optimised test score: {opt}  (baseline {base})")

    out_dir = HERE / "results"
    compiled.save(str(out_dir / "dspy_stage3_program.json"))
    (out_dir / "dspy_stage3_report.json").write_text(json.dumps({
        "model": args.model, "auto": args.auto,
        "split_personas": splits["personas"],
        "test_score_baseline": base, "test_score_optimised": opt,
        "thresholds": OPT_TH, "yellow_gate": GATE,
        "metric": "end-to-end ordinal zone match, single-day Stage-4 rules",
    }, ensure_ascii=False, indent=2))
    print("wrote results/dspy_stage3_program.json + dspy_stage3_report.json")


if __name__ == "__main__":
    main()
