# Prior chapter-4 results — gpt-oss-20b corpus (preserved)

These are the chapter-4 results established **before** the 2026-05-19 switch of
the working corpus to deepseek-v3.2 / gpt-oss-120b (see memory
`project_chapter4_working_corpus_120b`). E8/E9 build on the new corpora and are
**not directly comparable** to the figures below. This file preserves the
gpt-oss-20b baseline so the corpus switch does not erase it.

## Corpus

gpt-oss-safeguard:latest (Stage 2) + gpt-oss:latest (Stage 3), thematic calendar
(pre-E9 `_format_calendar`), generator qwen36, temperature 0.

Eval files (in `results/corpus/`):
`20260518_143235`, `20260518_193121`, `20260518_224319` (dmitry 17d + rina 10d),
`20260518_230850` (dmitry re-run, day-12 temp-bump fix).

## Stage-4 threshold optimisation (`threshold_optimization.gptoss20b.json`)

Persona split seed 42 (12 calibration / 4 holdout), yellow_gate 2.
Optimised thresholds: **uniform 0.25** on all five primaries
(tc/dd/ea/si/ei), pair thresholds 0.15, delusional 0.5, selfharm 0.4.

| Arm | Split | zone_match | macro_F1 | YELLOW F1 | fpr_green |
|---|---|---|---|---|---|
| default | calibration | 0.6545 | 0.5765 | 0.2353 | 0.0597 |
| default | holdout | 0.6441 | 0.4626 | 0.0 | 0.0606 |
| optimised | calibration | 0.6963 | 0.6502 | 0.4211 | 0.0597 |
| optimised | holdout | 0.7627 | 0.6721 | 0.5385 | 0.0606 |

## Hysteresis (`hysteresis_experiment.gptoss20b.json`)

Best: **k_red 2 / k_yellow 1**. Escalation-timing MAE improved with hysteresis.

| Arm | zone_match | macro_F1 | YELLOW F1 |
|---|---|---|---|
| optimised + hysteresis, holdout | 0.8305 | 0.7547 | 0.6897 |
| consolidated all-16 (pre-DSPy) | 0.732 | 0.7048 | 0.5565 |

## DSPy Stage-3 prompt optimisation (E1)

No-op: baseline vs MIPRO-compiled Δ0.0 on train/dev/test (81.89 / 69.53 / 80.0).
See `dspy_stage3_split_eval.json` (annotated `calendar: off`, confounded
calendar-off datapoint — not a clean ablation arm).

## Calendar treatment of all runs to date

Every gpt-oss-20b corpus run above used the calendar **ON, thematic-only**. There
is no clean calendar-OFF run at a fixed model. The only calendar-off datapoint
(DSPy E1) is confounded. The clean E9 ablation must be produced fresh.
