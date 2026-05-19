# Chapter 4 — State of Knowledge (2026-05-19)

A consolidated record of how the safety pipeline works, every experiment run so
far, what each one verified or falsified, and what the whole picture tells us.
Written so it can be read without the code open.

## The system under test

The pipeline is a four-stage behavioural-monitoring system. A user talks to an
AI assistant; the pipeline reads those conversations and, once per day, decides
whether the user is in a healthy state (GREEN), showing early concerning
patterns (YELLOW), or in acute risk (RED).

**Stage 1 — temporal metrics.** Deterministic. Looks only at message timestamps:
how often the user writes, at what hours, how that compares to their own recent
baseline. No LLM. Produces numbers like night-time message share and
frequency-vs-baseline ratio.

**Stage 2 — danger classifier.** An LLM reads each conversation session and
scores five clinical danger classes — suicide, psychosis, depression, obsession,
anthropomorphism — each with a label (present/absent) and a confidence 0–1. The
per-session results are aggregated into a daily danger summary (`danger_class_agg`).

**Stage 3 — behavioural scoring.** An LLM reads the day's sessions and rates
seven behavioural dimensions 0–1: topic concentration, decision delegation,
social isolation, emotional attachment, emotional isolation, delusional thinking,
self-harm. It also receives a *longitudinal calendar* — a list of prior notable
days — so days are not judged in isolation. This is Sonya's calendar mechanism.

**Stage 4 — risk engine.** Deterministic. Takes the Stage-1/2/3 outputs and
applies threshold rules to assign GREEN/YELLOW/RED. It also applies *hysteresis*:
a zone only escalates upward after the trigger persists for k consecutive days
(k_red, k_yellow), which suppresses one-day spikes.

**Calibration discipline.** Sixteen synthetic personas are split — twelve for
calibration (tuning), four held out for evaluation (never seen by any tuning
step), stratified by trajectory class, fixed seed 42. Every tuned number is fit
on calibration and reported with the calibration-minus-holdout gap.

## The evidence base

**Synthetic persona corpus.** Sixteen author-constructed personas across four
classes — control, escalation, recovery, sustained-YELLOW — each a multi-day
message trajectory with a designed expected zone per day (~250 day-points). It is
internally consistent but author-built, so it cannot by itself prove the pipeline
works on real people.

**MindGuard test set.** 1134 conversation turns labelled by clinicians
(`swordhealth/MindGuard-testset`). This is the *one* dataset with non-author
ground truth — the external check on the Stage-2 classifier.

## Experiments and verdicts

### Stage-4 threshold optimisation — VERIFIED

Re-fitting the YELLOW thresholds (Youden's-J initialisation, then coordinate
descent, macro-F1 objective with a no-worse false-positive constraint)
substantially improves zone accuracy. On the gpt-oss-20b corpus, holdout macro-F1
moved default 0.46 → optimised 0.67. **The deterministic rule engine works and is
tunable.** This is a solid positive result.

### Hysteresis — VERIFIED

Requiring k consecutive trigger-days before an upward zone change improves both
zone-match and escalation-timing accuracy. Optimum **k_red = 2, k_yellow = 1**;
escalation-timing mean absolute error fell 3.88 → 1.75 days on the deepseek
corpus. With hysteresis, gpt-oss-20b holdout reached zone-match 0.83 / macro-F1
0.75. The optimum is **stable across corpora** (held when re-fit on deepseek).
A genuine positive result.

### MindGuard external validation — WEAK external validity (with a taxonomy caveat)

The Stage-2 classifier was run over the 1134 clinician-labelled turns with three
models:

| Model | Binary-gate F1 | Recall | Precision | FPR on safe |
|---|---|---|---|---|
| gpt-oss-safeguard | 0.27 | 0.31 | 0.24 | 0.038 |
| deepseek-v3.2 | 0.21 | 0.33 | 0.15 | 0.071 |
| nemotron-3-120b | 0.13 | 0.40 | 0.08 | 0.187 |

**Read these numbers with the taxonomy caveat.** MindGuard's labels — safe /
unsafe_self_harm_risk / harm_to_others — do not align cleanly with the pipeline's
five classes (suicide, psychosis, depression, obsession, anthropomorphism). In
particular `harm_to_others` (22 rows) has **no corresponding class** — the
classifier was never designed to catch it, yet those rows count against the
binary unsafe/safe gate. The binary-gate F1 therefore **understates** the
classifier on the targets it actually has; it is not a clean falsification.

The fairer, within-taxonomy number is **self-harm recall: 0.65–0.80** — the
classifier catches most explicit self-harm turns. That is a moderate, honest
result, not a failure.

What the binary gate *does* fairly show: no model is simultaneously sensitive and
precise — the one with the highest recall (nemotron) pays a 19% false-positive
rate on safe turns. So the conclusion is **weak-to-moderate external validity**,
and a clear signal that **the synthetic-corpus classifier numbers should not be
read as real-world performance** — not a flat "the classifier fails."

**Rerun dependency — resolved.** These runs used the v1 classifier prompt
(`MULTI_LABEL_POLICY_PROMPT`, sha256 690c3dc6…). E8b found the graded v2 prompt
near-null, so v2 is not adopted and **no MindGuard v2 re-run is needed** — the
v1 numbers above stand.

### DSPy Stage-3 prompt optimisation (E1) — FALSIFIED

MIPROv2 prompt optimisation of the Stage-3 scorer produced a **no-op**: compiled
vs baseline Δ0.0 on train, dev, and test (81.89 / 69.53 / 80.0). MIPRO never
found a candidate beating the hand-written prompt. Reshaping the Stage-3 prompt
does not move the outcome. (The run also incidentally produced one calendar-off
datapoint, but confounded — different model, metric and split — so it is kept as
an observation, not a clean ablation arm.)

### E8a — Stage-2 replay recalibration — FALSIFIED (near-null)

Re-deriving the danger labels from stored confidences with grid-searched cutoffs,
then replaying Stage 4, improved macro-F1 by only **+0.01** (0.567 → 0.577); the
GREEN false-positive rate stayed at 0. Confidence-cutoff recalibration cannot
recover signal the classifier never emitted. Consistent with the diagnosis below.

### E8b — Stage-2 graded-prompt re-run — FALSIFIED (near-null)

Stage 2 was re-run with a graded-confidence prompt variant (explicit middle-band
instruction + worked moderate examples for depression and obsession), then Stage 4
replayed over frozen Stage-1/3. Against the v1 deepseek baseline (both scored
through the optimised Stage-4 thresholds):

| Split | v1 macro-F1 | v2 macro-F1 | v1 YELLOW-F1 | v2 YELLOW-F1 |
|---|---|---|---|---|
| calibration | 0.567 | 0.578 (+0.010) | 0.290 | 0.314 (+0.024) |
| holdout | 0.718 | 0.718 (+0.000) | 0.621 | 0.621 (+0.000) |

The graded prompt recovers four YELLOW day-points on calibration and **exactly
zero** on holdout — the holdout split is byte-identical. The YELLOW-silence is
**not a promptable gap**. This closes the prompt-level lever: E1 (DSPy), E8a
(recalibration) and E8b (graded prompt) all return null. No MindGuard v2 re-run
is warranted, since v2 is not worth adopting.

### E9 — Calendar on/off ablation — near-null; stability claim FALSIFIED

The clean three-arm test of Sonya's calendar mechanism, all on deepseek-v3.2:
calendar off / thematic (calendar on, pre-E9 format) / score-anchored.

| Arm | zone_match | macro-F1 | FPR-on-GREEN | mean score-std |
|---|---|---|---|---|
| off (no calendar) | 0.628 | 0.528 | 0.01 | **0.167** |
| thematic (calendar on) | 0.640 | 0.554 | 0.00 | 0.173 |
| anchored (score digest) | 0.640 | 0.552 | 0.00 | 0.172 |

Two findings, both negative:

- **Zone accuracy: near-null.** Turning the calendar on lifts zone_match by
  +0.012 and macro-F1 by +0.026 over off — a marginal gain, within the range of
  run-to-run noise. The score-anchored refinement adds **nothing** over plain
  thematic (0.640 = 0.640; macro-F1 −0.002).
- **Stability claim: falsified.** The calendar's stated purpose is to suppress
  day-to-day score variance. It does not — calendar-*off* has the **lowest**
  mean score-std (0.167); turning the calendar on slightly *raised* variance,
  and anchoring did not pull it back. The longitudinal context does not
  stabilise Stage-3 scoring.

**Scope of the claim — important.** E9 varied calendar on/off and calendar
*content* (thematic vs. score-anchored). It held constant the *channel*
(textual, in-prompt), the *consumer* (the Stage-3 LLM), and the *form of use*
(advisory). What is falsified is therefore narrow: **passing longitudinal
context as text into the Stage-3 LLM prompt does not improve scoring or suppress
variance.** This is *not* a falsification of longitudinal context in general.
Untested and still open: deterministic post-hoc smoothing of the Stage-3 score
series (EWMA / moving average), score-as-prior shrinkage, longitudinal context
at other stages, and non-flat temporal structure (change-points, weekly
rollups).

In fact the evidence on the *other* side of the channel split is positive:
hysteresis (Stage 4, deterministic, k prior days) is VERIFIED, and Stage-1's
7-day rolling baselines are deterministic longitudinal context that works. The
sharper conclusion: **longitudinal context delivered through the LLM prompt
fails; longitudinal context applied deterministically works** — the delivery
channel is the discriminator.

**Caveat:** the ablation measures zone accuracy and score stability, not
escalation-*timing*. A calendar effect on timing is not excluded by this run.

### Model sensitivity (E10-equivalent) — gpt-oss-120b VERIFIED (no model-capacity gap)

A full-corpus run on gpt-oss-120b tests whether the residual error is model
capacity. After correcting a data-aggregation bug (see below), the verdict is
clear: **a stronger model does not change the picture.**

| Model | zone_match | macro-F1 | GREEN-F1 | YELLOW-F1 | RED-F1 | FPR-on-GREEN |
|---|---|---|---|---|---|---|
| deepseek-v3.2 (working corpus) | 0.68 | 0.62 | 0.79 | 0.39 | 0.68 | 0.00 |
| gpt-oss-120b (re-scored) | 0.72 | 0.69 | 0.81 | 0.56 | 0.71 | 0.03 |

gpt-oss-120b is marginally *better* than deepseek, not worse, and notably lifts
YELLOW-F1 (0.39 → 0.56) — but it is still the weakest band, and the gain is well
short of "solved." **The residual error is not a model-capacity problem**: a
much larger model neither breaks the pipeline nor fixes YELLOW. This converges
with the prompt-level nulls — the limitation is structural, not capacity.

**Aggregation bug found and fixed (the false E10 result).** The first read of
this run reported gpt-oss-120b *catastrophically over-escalating* — 234/250
day-points RED, FPR-on-GREEN 0.86. That was an artifact, not model behaviour.
`_aggregate_predictions` in `danger_agg.py` used the Stage-2 `confidence` field
directly as danger severity, never gated by `label`. The pipeline silently
assumed `label=0 ⟹ confidence≈0`. deepseek and gpt-oss-20b happen to honour that
(they emit `confidence 0.0` for absent classes); gpt-oss-120b reads "confidence"
as *confidence in its decision* and emits `label=0 / confidence=0.96` ("96% sure
this danger is absent"). The aggregator misread 0.96 as severe danger and the
risk engine fired RED on clean days. Fix: gate confidence by label —
`danger = confidence if label==1 else 0.0`. Verified: a no-op on the deepseek
corpus (byte-identical), and it takes gpt-oss-120b from 0.35 → 0.72 zone_match.
viktor alone went 0.57 → **1.00**. The corrected scores are in
`experiments/results/gptoss120b_rescored_postfix.json`.

This is itself a chapter-4 lesson: an unstated cross-component contract (here,
what `confidence` means when `label=0`) is a latent failure that stays invisible
until a model interprets the under-specified prompt differently.

### E11 — Stage-4 noise spikes — ensemble VERIFIED, smoothing/hysteresis null

Three zero-cost offline replays over the existing corpus
(`experiments/stage4_noise_spikes.py`), all run on top of the consolidated
baseline (optimised thresholds + verified hysteresis k_red=2 / k_yellow=1).
Hyperparameters grid-searched on calibration, reported on holdout.

| Arm | calib zone / macro-F1 / YELLOW-F1 | holdout zone / macro-F1 / YELLOW-F1 |
|---|---|---|
| baseline | 0.649 / 0.606 / 0.395 | 0.848 / 0.785 / 0.710 |
| sticky hysteresis (k_down=3) | 0.660 / 0.630 / 0.481 | 0.814 / 0.711 / 0.621 |
| EWMA smoothing (best α=1.0) | 0.649 / 0.606 / 0.395 | 0.848 / 0.785 / 0.710 |
| ensemble (deepseek + 120b) | 0.654 / 0.635 / **0.505** | **0.915 / 0.847 / 0.889** |

- **Sticky (asymmetric) hysteresis — weak/mixed.** Requiring k_down consecutive
  lower days before de-escalating recovers calibration YELLOW-F1 (0.40 → 0.48)
  but the grid overfits: holdout *regresses* (YELLOW-F1 0.71 → 0.62) and GREEN
  false-positives appear. Not a clean win.
- **EWMA score smoothing — null.** The best smoothing factor is α=1.0, i.e.
  *no smoothing*. Temporal cross-day smoothing does not help — this also closes
  the "deterministic calendar" idea: the recoverable noise is not on the
  day-to-day axis.
- **Cross-model ensemble — VERIFIED.** Averaging Stage-2 (re-aggregated from
  raw) and Stage-3 across deepseek-v3.2 and gpt-oss-120b lifts both splits;
  holdout YELLOW-F1 0.71 → 0.89, macro-F1 0.79 → 0.85.

**The decisive finding.** Ensembling helps strongly; EWMA does not. So the
per-model, per-day Stage-3 error is **independent stochastic noise** —
recoverable by averaging across models/samples *on the same day*, but not by
smoothing *across days* (which only blurs real transitions). This is the first
genuinely positive lever for the YELLOW band: multi-sample / ensemble scoring,
not a temporal filter. Caveat: the holdout is 4 personas (~59 day-points), so
0.915 sits on a small n; the calibration YELLOW-F1 gain 0.40 → 0.51 is the more
trustworthy signal.

## The diagnosis these results converge on

The pipeline's **deterministic parts work**. Stage 1, the Stage-4 rule engine and
hysteresis all behave well and are tunable; the threshold and hysteresis results
are solid.

The pipeline's **LLM parts are the weak points**, and prompt-level fixes do not
repair them:

- **Stage 2 has only weak-to-moderate external validity** (MindGuard — read with
  the taxonomy caveat) and is **silent on most YELLOW days** in the corpus (~58%
  zero output). Over half the danger-keyed Stage-4 rules therefore rarely fire —
  their input is empty.
- **Stage 3 is noisy, not biased.** Per-zone score means separate correctly, but
  day-to-day variance is high — a steady persona's score can swing across a
  threshold on consecutive days for no real reason. The in-prompt longitudinal
  calendar (E9), meant to suppress that variance, does not — calendar-off is the
  *least* noisy arm. Deterministic smoothing of the score series is untested and
  remains the open lever.
- **Prompt optimisation is exhausted as a lever.** E1 (DSPy), E8a
  (recalibration) and E8b (graded prompt) all came back null. The limitation is
  not the wording.
- **Model capacity is not the lever either.** gpt-oss-120b (E10) is marginally
  better than deepseek but far short of solving YELLOW. The limitation is
  structural.
- **The one positive lever found: multi-sample / ensemble scoring.** E11 shows a
  large share of the YELLOW collapse is independent per-day stochastic noise,
  recoverable by averaging Stage-3 across models (or, by extension, repeated
  samples). This does not fix the silent Stage-2 classifier, but it is the first
  intervention that materially moves YELLOW.

**Net:** the pipeline does not reliably hold the YELLOW band — roughly a third of
YELLOW-designed day-points collapse to GREEN or RED. The honest chapter-4 story
is a sound architecture with rigorous calibration discipline, whose LLM
components are not yet reliable enough — and whose true performance on real
clinician data is materially worse than the synthetic corpus suggests.

## Caveat on the current corpus

Local-GPU limits forced the chapter-4 working corpus from gpt-oss-20b to
deepseek-v3.2 / gpt-oss-120b. E8/E9 are therefore not directly comparable to the
earlier E1–E7 gpt-oss-20b results. The gpt-oss-20b baseline is preserved in
`experiments/results/PRIOR-RESULTS-gptoss20b.md`. The results chapter must state
this break in comparability.
