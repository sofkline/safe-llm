# Upstream YELLOW-band repair — design (E8–E10)

## Context and problem

Chapter 4's organising finding is that the pipeline does not hold the YELLOW
zone. After the Stage-4 recalibration (thresholds collapsed to a uniform 0.25,
hysteresis k_red=2 / k_yellow=1) the consolidated all-16 result is zone-match
0.732, macro-F1 0.705, YELLOW F1 0.56 — roughly a third of YELLOW-designed
day-points still collapse to GREEN or RED.

The DSPy Stage-3 prompt optimisation (E1) is a clean **no-op**: baseline vs
MIPRO-compiled is Δ0.0 on all three splits (train 81.89, dev 69.53, test 80.0).
MIPRO never found a candidate beating the un-optimised baseline, so the saved
program is effectively the seed. Reshaping the Stage-3 prompt does not move the
zone outcome.

A corpus audit locates the residual fault **upstream of the Stage-3 prompt**:

- **Stage 3 is noisy, not biased.** Per-zone `behav_max` means separate cleanly
  (GREEN 0.11 / YELLOW 0.50 / RED 0.73). The central tendency is correct; the
  failure is day-to-day *variance* — a steady sustained-YELLOW persona (dmitry)
  swings `decision_delegation` 0.4 → 0.05 → 0.2 on consecutive days, crossing
  the 0.25 threshold each way. Prompt rewrites cannot reduce variance.
- **Stage 2 is silent on most YELLOW days.** The 5-class danger classifier
  outputs zero on 44 of 76 YELLOW day-points (58%); `max_class_avg` means by
  zone are GREEN 0.04 / YELLOW 0.16 / RED 0.46. Yet `risk_engine.py` carries ~6
  YELLOW/RED triggers keyed off `danger_class_agg` — over half the danger-keyed
  rule logic never fires because its input is empty.
- **Sonya's longitudinal calendar exists but carries no numeric memory.** Her
  design specifies a «механизм лонгитюдного календаря»: Stage 3 receives today's
  sessions plus a calendar of significant prior days, explicitly so that days
  are not analysed in isolation. The corpus harness *does* run the calendar
  (`stage3_behavioral(..., calendar[-14:], ...)`), but `_format_calendar`
  renders only thematic fields — `Topics | Events | Tone | Markers`. It carries
  no prior-day behavioural scores and no prior zone. Stage 3 therefore re-derives
  the seven scores fresh each day with thematic continuity but no numeric anchor
  — the direct cause of the variance above.

So the YELLOW repair has two upstream targets and one optional probe.

## E8 — Stage-2 classifier repair (replay + re-run)

Stage 2 has two distinct faults; each needs a different method.

**E8a — replay recalibration (over-confidence → false RED).** The Stage-4 RED
triggers `psychosis_max > 0.8`, `suicide_flag_rate > 0`, `psychosis_flag_rate`
fire on max-confidence labels the classifier emits on mild days (Sonya's named
fault — false RED collapse). Replay `danger_agg` aggregation over the *stored*
per-session predict JSON with re-fit flag thresholds / confidence calibration.
No model calls.
*Prerequisite:* the corpus `*_corpus_eval.jsonl` rows store only
`danger_class_agg`, not the raw per-session predict dicts. The harness must be
extended to persist raw per-session predict JSON before E8a can replay.

**E8b — re-run (silence on YELLOW).** A zero output cannot be recalibrated — the
signal is absent, not miscalibrated. Re-run Stage 2 over the corpus with a
revised `MULTI_LABEL_POLICY_PROMPT` that grades moderate distress instead of
emitting near-binary labels, and/or a stronger classifier model. Compare the
YELLOW nonzero-rate and the zone metrics against the current
`gpt-oss-safeguard:latest` baseline.

Calibration discipline: the existing 12-calibration / 4-holdout persona split
(seed 42); re-fit on calibration, report the calibration−holdout gap.

## E9 — Calendar score-anchoring (Sonya's longitudinal calendar)

Give the calendar the numeric memory it currently lacks.

- Extend the calendar entry and `_format_calendar` (`src/behavioral/`) to carry
  a compact prior-day numeric digest — the seven scores, or `max score + which
  dimension`, plus the prior zone — alongside the existing thematic fields.
- Update the Stage-3 prompt instruction to anchor today's intensity to the
  calendar trend rather than swinging without cause.
- Re-run Stage 3 over the corpus.

Primary metric: per-persona score *stability* — the standard deviation of each
dimension across a persona's steady phase — plus the zone metrics. Success is
reduced variance on sustained personas with no regression in GREEN
false-positive rate.

**Calendar ablation (built into E9).** E9 runs Stage 3 twice over the corpus
under otherwise identical conditions — same model, same metric, same persona
split — once with the calendar disabled (`calendar=[]`) and once with the
score-anchored calendar. This is the controlled calendar-on/off ablation: it
isolates the longitudinal mechanism's contribution, which is the central claim
of Sonya's design and currently untested.

DSPy E1 already produced a *calendar-off* datapoint (`calendar_text=""`), but a
**confounded** one — it also differs from every calendar-on run in model
(deepseek-v3.2 vs gpt-oss), metric (ordinal-credit single-day rules vs
exact-match with hysteresis) and persona split. It is preserved as a prior
observation, not a clean ablation arm; the clean arm is E9's.

## Existing results to preserve

The E1 run is a negative result *and* an incidental calendar-off observation —
neither must be lost. The following artefacts are kept and explicitly labelled
as **"Stage 3, calendar OFF, deepseek-v3.2, MIPRO light"**:

- `results/dspy_stage3_report.json`, `dspy_stage3_split_eval.json`,
  `dspy_stage3_program.json`, `dspy_stage3_run.log`,
  `dspy_stage3_split_eval.log`.

A `results/dspy_stage3_split_eval.json` annotation (a `"calendar": "off"` and
`"ablation_note"` field) records the interpretation so a later reader does not
mistake it for a calendar-on baseline. The chapter-4 docs cite E1 both as the
prompt-optimisation no-op and as the (confounded) calendar-off prior.

## E10 (optional) — Stage-3 model-swap smoke

Re-score viktor, sara, nastya with a stronger Stage-3 model (deepseek-v3.2 via
RouterAI) at temperature 0 and measure score stability against
`gpt-oss:latest`. This decides whether the variance is model capacity rather
than missing context. Smoke only — it informs E9, it does not gate it.

## Sequencing and constraints

Order: persist raw per-session predict JSON (harness code) → E8a replay (no
GPU) → E8b re-run → E9 source change + Stage-3 re-run → E10 smoke.

E8b and E9 both make model calls. Strict sequential on the local GPU — no two
Ollama jobs in parallel (VRAM exhaustion stalls Ollama). The Windows box
(192.168.87.25) is off-limits.

E8a touches the `danger_class_agg` flag thresholds that `risk_engine.py`
consumes. The Stage-4 optimum (uniform 0.25, k_red=2 / k_yellow=1) was a
robustness result measured on a *silent-Stage-2* corpus. After E8 and E9 land,
re-run `optimize_thresholds.py` and `hysteresis_experiment.py` to re-confirm it
— a Stage 2 that stops being silent may shift the optimum.

## Testing

Each experiment writes a results JSON following the existing
`threshold_optimization.json` / `dspy_stage3_split_eval.json` conventions, with
the calibration/holdout split honoured and the gap reported. Stage-4
re-validation after E8+E9 as above.

## Out of scope (YAGNI)

- E1 DSPy re-run — no-op established.
- E7 — redundant; cite the DSPy 80.0 → 80.0 / Δ0.0 table directly.
- Stage 1 temporal metrics — deterministic, separate cleanly by zone, no
  evidence of fault.
