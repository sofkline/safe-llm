# Chapter 4 — Experimental Validation (draft)

**Draft, English, 2026-05-19.** This fills the structure of `chapter4-scaffold.md`
(revised 2026-05-19) with the experiments run through 2026-05-19. It is a working
draft for Sonya to revise and translate into Russian — the numbers are real, the
prose is a starting point. Where the move of the working corpus from gpt-oss-20b
to deepseek-v3.2 means a figure must be re-derived, this is flagged inline.

The chapter answers two questions, not one. The first — *does the four-stage
pipeline reproduce the designed behaviour of the personas?* — is the original
validation question (claims C1–C5, §4.3–4.6). Checking it surfaced a stable weak
spot: the pipeline does not hold the YELLOW zone. That finding spawned the second
question — *given the YELLOW collapse, which intervention repairs it?* — answered
by an ablation of interventions (§4.7), one of which (C6) is a direct test of the
longitudinal-calendar mechanism, the central design contribution of Chapter 2.

---

## 4.1 Experimental setup and claims

This chapter tests the four-stage behavioural-monitoring pipeline of Chapter 2.
The **unit of observation** is a *persona* — a designed profile of expected
behaviour over a fixed number of days, not a real user. The **unit of
measurement** is the *day-point*: the risk zone (GREEN / YELLOW / RED) the
pipeline assigns to one persona on one day. Sessions are synthetic, generated
from persona day-scripts (§4.2).

The chapter checks six claims in two families. Every claim is stated so that it
can be falsified, and the positive outcome of each was fixed before the runs.

**Family A — does the method reproduce the designed behaviour.**

- **C1 (escalation).** On escalation personas the pipeline reproduces the designed
  zone trajectory, and the first transition into RED occurs within ±1 day of the
  designed day.
- **C2 (control).** On control personas the pipeline stays in GREEN for the whole
  arc.
- **C3 (recovery).** On the recovery persona, after behaviour stabilises, the
  pipeline returns from YELLOW to GREEN within the designed window.
- **C4 (sustained YELLOW).** On the sustained-YELLOW persona the pipeline holds
  YELLOW and does not escalate to RED in the absence of a RED trigger.
- **C5 (external generalisation).** On clinician-labelled real dialogue the
  classifier's safe/unsafe gate keeps the false-positive rate on safe turns low
  while recalling clinician-flagged self-harm.

**Family B — can the YELLOW collapse be repaired.** Each candidate intervention
is itself a falsifiable claim of the form *"intervention X lifts holdout YELLOW-F1
above the baseline."* One of them is singled out because it tests an
own-contribution rather than a side optimisation:

- **C6 (longitudinal calendar).** Passing longitudinal context as text into the
  Stage-3 prompt — the *calendar* mechanism of Chapter 2 — improves Stage-3
  behavioural scoring and/or suppresses day-to-day score variance.

C1–C4 are checked on the synthetic corpus (§4.3–4.5); C5 on an external
clinician-labelled dataset (§4.6); C6 and the other Family-B levers in §4.7.
§4.8 collects the verdicts; §4.9 draws the conclusions.

A note required up front: the risk-engine thresholds (Chapter 2, Stage 4) and the
persona archetypes were designed together — the personas carry per-phase *target*
metrics that the thresholds were set against, and all sixteen personas were
available when the thresholds were set. The synthetic-corpus experiments are
therefore **closer to a calibration-convergence check than to an independent
evaluation**, except where a held-out persona split is used explicitly (§4.7).
The only genuinely external test is §4.6. This distinction is carried through
every section below.

---

## 4.2 Method

**Persona as unit of observation.** A persona is a profile of expected behaviour:
a backstory, a day-by-day designed trajectory of risk phases, and a target
behavioural pattern per phase. Sixteen personas span five classes — escalation
(e.g. Viktor: GREEN→YELLOW→RED over 14 days), control (e.g. Sara: GREEN for 14
days), recovery (Elena: GREEN→YELLOW→GREEN), sustained-YELLOW (Dmitry:
GREEN→YELLOW held without RED) and borderline (Nastya: YELLOW pushed to the edge
of RED). Each class operationalises a risk pattern from Chapter 1. The corpus has
roughly 250 day-points.

**Calibration vs evaluation.** The sixteen personas are split — twelve for
calibration, four held out for evaluation — stratified by trajectory class with a
fixed seed. Every tuned parameter in §4.7 is fit on calibration only and reported
with the calibration-minus-holdout gap. The §4.3–4.5 trajectory experiments use
the full sixteen, so their numbers are read as calibration-convergence, not
independent evaluation.

**Session generation.** From a persona day-script, synthetic user/assistant
dialogues are generated, one or more sessions per day. Two generator models were
used — DeepSeek V3.2 and qwen3.6 — which lets §4.8 report whether pipeline
verdicts depend on the generator.

**Pipeline run.** The harness `evaluate_corpus.py` replays each persona's sessions
through the four stages: Stage 1 (temporal metrics, deterministic), Stage 2
(5-class danger classification per session, aggregated), Stage 3 (LLM behavioural
scoring of seven dimensions, with the longitudinal calendar), Stage 4 (the
deterministic risk-zone rule engine, with hysteresis). It reuses the production
stage logic verbatim and substitutes only the data-access layer. Temperature is
fixed at 0 for repeatability.

**Disclosure — corpus and model change.** The chapter-4 working corpus was moved,
mid-programme, from the local model gpt-oss-20b to deepseek-v3.2 (with a
gpt-oss-120b cross-check), because of local-GPU limits. Early experiments (the
gpt-oss-20b runs) and later ones (E8–E11, on deepseek) are therefore **not
directly comparable**; the gpt-oss-20b baseline is preserved separately. Each
result below states which corpus it is on.

**Disclosure — aggregation defect.** During the work a defect was found in the
Stage-2 aggregator: the `confidence` field was used as a danger severity without
being gated by the `label` field. The defect, its discovery and its fix are
described in §4.7.2 as a chapter lesson; it affected an intermediate
gpt-oss-120b read and was corrected before the E10 verdict.

**Metrics.** Each with a formal definition:
- *zone-match rate* — day-points whose predicted zone equals the designed zone,
  over all day-points;
- *macro-F1* — unweighted mean of the per-zone F1 over {GREEN, YELLOW, RED}, so
  the rare YELLOW band counts equally;
- *YELLOW-F1* — the per-zone F1 for YELLOW, reported separately because YELLOW is
  the band under investigation;
- *false-positive rate on GREEN* — GREEN-designed day-points predicted YELLOW or
  RED, over all GREEN-designed day-points;
- *day of first RED* — the first day a persona is predicted RED, vs the designed
  day;
- *full-trajectory exact-match rate* — personas whose entire predicted sequence
  equals the designed one;
- for the external set — *binary-gate precision / recall / F1* and *self-harm
  recall*.

**Reproducibility.** Every run writes a `summary.json` recording the varied and
fixed variables — models, hosts, temperature, prompt hashes, dataset revision,
git SHA. Persona day-scripts, prompt versions and thresholds are in the
repository. The appendix lists the exact artefacts and the canonical experiment
numbering.

---

## 4.3 Experiment — zone trajectories on polar personas (C1, C2)

**Conditions.** Sixteen personas, deepseek-v3.2 working corpus, fixed
configuration of §4.2, default (hand-set) Stage-4 thresholds. The polar cases are
Viktor (escalation, 14 days, designed GREEN×3→YELLOW×3→RED×8) and Sara (control,
14 days, designed GREEN throughout): they bound the method — "reacts to a
sustained worsening pattern" and "does not react to its absence".

**Observation.** Aggregate over all sixteen personas (≈250 day-points):

| | value |
|---|---|
| zone-match rate | 0.64 |
| macro-F1 | 0.55 |
| per-zone F1 | GREEN 0.76 · YELLOW 0.22 · RED 0.68 |
| false-positive rate on GREEN | 0.00 |
| full-trajectory exact match | 3 of 16 |

Confusion matrix (rows designed, columns predicted):

| designed ↓ | GREEN | YELLOW | RED |
|---|---|---|---|
| GREEN (100) | 100 | 0 | 0 |
| YELLOW (76) | 43 | 10 | 23 |
| RED (74) | 21 | 3 | 50 |

Viktor: zone-match 0.79, designed first RED day 7, predicted day 4. Sara:
zone-match 1.00, GREEN throughout as designed.

**Reading.** GREEN and RED are recovered reasonably (F1 0.76 and 0.68). YELLOW is
not: of 76 YELLOW-designed day-points only 10 are predicted YELLOW — 43 collapse
down to GREEN, 23 jump up to RED. The middle band is squeezed out from both
sides. Only three of sixteen personas have their full trajectory reproduced
exactly: over 14–17 day-points a single divergence breaks the match.

**Interpretation against the claims.** C1 is **not confirmed**: escalation
personas reach RED, but the timing clause fails (§4.4). C2 is **confirmed** in the
control-side reading on this corpus — all 100 GREEN-designed day-points are
predicted GREEN — but the full-arc clause is examined again in §4.5 across all
control personas.

**Threats to validity.** The thresholds were set with these personas in view, so
the matching parts are calibration-convergence, not independent evaluation. The
GREEN/YELLOW/RED counts depend on the generator and the serving backend (§4.8).

---

## 4.4 Experiment — borderline, recovery and sustained-YELLOW scenarios (C3, C4)

This section holds the chapter's main Family-A negative results and states the
finding that organises the rest of the chapter.

**The escalation timing failure.** On escalation personas the pipeline reaches
RED, but **earlier than designed**, almost without exception (deepseek working
corpus, day of first RED):

| Persona | designed | predicted |
|---|---|---|
| viktor | 7 | 4 |
| brook | 8 | 4 |
| masha | 8 | 4 |
| james | 10 | 7 |
| oleg | 11 | 5 |
| dasha | 12 | 5 |
| joseph | 13 | 10 |
| arkady | 15 | never |
| amanda | 6 | never |

Every escalation persona fires RED several days early — or, for `arkady` and
`amanda`, never escalates at all. C1's "±1 day" clause is therefore **not
confirmed**.

**The recovery failure.** Elena is designed to rise into YELLOW and then return to
GREEN. The pipeline escalates her early and does not reproduce the recovery shape.
C3 is **not confirmed**.

**The sustained-YELLOW failure.** Dmitry is designed to hold YELLOW for two weeks
with no RED trigger — built precisely to probe the Stage-4 rule "sustained
YELLOW ≥ 3 days → RED". The pipeline escalates him to RED. Nastya, the borderline
persona designed to sit at the edge of RED without crossing it, shows the
opposite failure on the deepseek corpus — every one of her six YELLOW days
collapses *down* to GREEN. C4 is **not confirmed**, and the YELLOW band fails in
*both* directions depending on the persona.

**Mechanism — a Stage-4 audit.** A targeted audit of the YELLOW-designed
day-points traces the collapse to two distinct, *opposite* causes.

*The day-points that jump to RED.* These are driven by high-confidence
single-message classifier triggers — on mild-distress days the Stage-2 classifier
returns *maximum-confidence* psychosis or suicide labels, and the Stage-4 RED
rules those scores trip are themselves reasonable. The fault is upstream, in the
classifier's confidence calibration on mild content. This is the same
over-aggression §4.6 measures on the external set, seen here at the *confidence*
level.

*The day-points that fall to GREEN.* These produce **zero** Stage-4 triggers — not
one short of the two-trigger YELLOW gate, but none. Yet Stage 3 does register the
distress: across these days the behavioural scores reach the moderate band
(topic-concentration up to 0.9, emotional-attachment up to 0.7, the isolation
signals 0.3–0.5). The signal exists; it lands *below every YELLOW threshold* — the
default rules require behavioural scores above 0.4–0.7, and genuine moderate
distress clears none of them.

**The finding that organises the chapter.** To trip the two YELLOW triggers the
gate demands, a day must score near the severe range — at which point the
over-confident classifier trips a RED rule first. Moderate distress is invisible
from below and pre-empted from above. The pipeline collapses the three-zone scheme
toward a GREEN/RED binary: YELLOW-F1 is 0.22, and only 10 of 76 YELLOW-designed
day-points survive as YELLOW. Repairing this collapse is the subject of §4.7.

---

## 4.5 Experiment — false-positive robustness (C2, control side)

**Question.** Does the system alarm ordinary users? Control personas — Sara,
Katya, Igor — are designed GREEN for their whole arc.

**Observation.** On the deepseek working corpus all 100 GREEN-designed day-points
are predicted GREEN: false-positive rate on GREEN **0.00**. (On the earlier
qwen3.6 corpus the same personas produced a 6 % stray-RED rate; the difference is
itself a generator/backend-sensitivity caveat — §4.8.)

**Reading.** On this corpus the system does not alarm calm personas at all. The
honest qualifier is that when false REDs *do* appear — as on the qwen3.6 corpus —
they are RED, not YELLOW: a calm day with one over-confident psychosis/suicide
label goes straight to the most severe zone. C2's control side is **confirmed on
the deepseek corpus**, with the generator-sensitivity caveat noted.

**Honest limit.** The corpus contains no purpose-built false-alarm provocations —
long technical sessions, night activity from a time zone, heavy but healthy use.
The control personas are ordinary-calm, not adversarially-calm. This section
establishes only that calm personas stay GREEN; the stronger false-positive
evidence is the external set (§4.6).

---

## 4.6 Experiment — external dataset (MindGuard) (C5)

This is the only experiment in the chapter on data the author did not construct.

**Dataset.** `swordhealth/MindGuard-testset` — 1134 clinician-labelled user turns
from real mental-health-adjacent dialogue: 1092 `safe`, 20 `unsafe_self_harm_risk`,
22 `harm_to_others`. The 5-class classifier was run over every turn with three
classifier models, to separate classifier error from model choice.

**Observation.**

| | gpt-oss-safeguard | deepseek-v3.2 | nemotron-3 |
|---|---|---|---|
| binary-gate F1 | 0.27 | 0.21 | 0.13 |
| recall | 0.31 | 0.33 | 0.40 |
| precision | 0.24 | 0.15 | 0.08 |
| FPR on 1092 safe turns | 0.038 | 0.071 | 0.187 |
| self-harm recall (of 20) | 0.65 | 0.70 | 0.80 |
| safe FP — depression class | 0 | 1 | 163 |

**Reading.**
- **Depression-class over-firing is model-specific, not a prompt fault.** nemotron
  flags depression on 163 of 1092 safe turns; gpt-oss-safeguard flags 0, deepseek
  1. A three-model sweep was needed to see this — on one model the 163 would have
  looked like a prompt defect.
- **A taxonomy mismatch depresses the binary F1.** MindGuard's labels do not align
  with the five classes: `harm_to_others` (22 rows) has *no* corresponding class
  and cannot be caught, yet counts against the unsafe/safe gate. The binary F1
  therefore *understates* the classifier on the targets it actually has.
- **The fair within-taxonomy number is self-harm recall: 0.65–0.80** — the
  classifier catches most explicit self-harm turns. No model is simultaneously
  sensitive and precise: the highest-recall model (nemotron, 0.80) pays a 19 %
  false-positive rate on safe turns.

**Interpretation against C5.** C5 is **partially confirmed**: with
gpt-oss-safeguard the false-positive rate on safe turns is low (3.8 %) and
self-harm recall is 0.65. The conclusion is weak-to-moderate external validity —
not "the classifier fails", but a clear signal that the synthetic-corpus
classifier numbers should not be read as real-world performance.

---

## 4.7 Repairing the YELLOW band — an ablation of interventions (Family B)

§4.4 found a specific defect: the pipeline collapses the YELLOW band. This section
asks which intervention repairs it. Each intervention is stated as a falsifiable
claim, tuned on the twelve calibration personas and reported on the four held-out
evaluation personas.

### 4.7.1 The longitudinal-calendar mechanism (C6)

The calendar — feeding each Stage-3 call a list of prior notable days so that days
are not scored in isolation — is the central design contribution of Chapter 2.
C6 states that this improves Stage-3 scoring or suppresses its day-to-day
variance. C6 was fixed as a falsifiable claim *before* the runs: the positive
outcome would be a calendar-on configuration with higher zone accuracy and lower
score variance than calendar-off.

**Experiment E9 — calendar on/off ablation.** A clean three-arm test on
deepseek-v3.2: calendar off / thematic (calendar on, prose format) / score-anchored
(calendar on, with a per-day score digest).

| Arm | zone-match | macro-F1 | FPR-on-GREEN | mean score-std |
|---|---|---|---|---|
| off | 0.628 | 0.528 | 0.01 | **0.167** |
| thematic | 0.640 | 0.554 | 0.00 | 0.173 |
| score-anchored | 0.640 | 0.552 | 0.00 | 0.172 |

Two negative findings. *Zone accuracy — near-null:* turning the calendar on lifts
zone-match by +0.012, within run-to-run noise; the score-anchored refinement adds
nothing over plain thematic. *Stability claim — falsified:* the calendar's stated
purpose is to suppress day-to-day score variance, and it does not — calendar-*off*
has the **lowest** mean score-std (0.167); turning the calendar on slightly
*raised* variance.

**Follow-up — a hand-authored calendar.** One alternative remained: perhaps the
calendar was simply badly formatted. The live calendar emits thematic prose with
no score trajectory, a non-comparable free-text tone field, repeated marker
blocks, and feeds the model its own past predicted zones as if they were ground
truth. A corrected calendar was hand-authored for two personas — explicit score
trajectory, an ordinal tone scale, day-over-day deltas, a trend header — and
Stage 3 was rerun with it. Zone accuracy did not move: Viktor 0.786 → 0.786,
Nastya 0.40 → 0.40. The corrected calendar perturbs the Stage-3 scores (it is
being read) but the perturbation is noise-shaped — bidirectional, never enough to
cross a Stage-4 threshold. This closes the formatting alternative: what is
falsified is the *mechanism*, not the prose.

**Verdict on C6 — not confirmed.** Passing longitudinal context as text into the
Stage-3 LLM prompt does not improve scoring and does not suppress variance.

**Scope of the falsification — important.** E9 varied calendar on/off and calendar
content, holding constant the *channel* (textual, in-prompt) and the *consumer*
(the Stage-3 LLM). What is falsified is therefore narrow: **longitudinal context
delivered through the Stage-3 LLM prompt fails.** This is *not* a falsification of
longitudinal context in general. The evidence on the other side of the channel
split is positive — Stage-4 hysteresis and Stage-1's 7-day rolling baselines are
both deterministic longitudinal context, and both work (§4.7.2). The sharper
conclusion: **longitudinal context applied deterministically works; the same
information delivered through the LLM prompt does not** — the delivery channel is
the discriminator.

**The profile is useful regardless of C6.** C6 tests one narrow use of the
longitudinal profile — whether it raises automated Stage-3 accuracy. Its
falsification does not make the profile worthless. The day-by-day profile the
calendar builds — topics, life events, emotional tone, relationship markers — is a
legible longitudinal record of a user, and as such it is a usable artefact for
**operator review** and a **source of heuristics** for future development,
independent of whether it helps the automated classifier. The negative C6 result
bounds one application of the mechanism; it does not retire the mechanism.

### 4.7.2 The other levers — summary ablation

Three foundational experiments and the rest of the Family-B levers, each a
falsifiable "lifts holdout YELLOW-F1" claim.

**Foundational — verified.** *Stage-4 threshold optimisation*: re-fitting the
hand-set YELLOW thresholds (Youden's-J initialisation, then coordinate descent on
macro-F1 with a no-worse false-positive constraint), and collapsing them to a
near-uniform 0.25 — the level at which calm and moderate-distress days actually
separate — substantially improves zone accuracy. *Hysteresis*: reporting an
upward zone change only after the trigger persists k consecutive days (optimum
k_red = 2, k_yellow = 1, stable across corpora) improves both zone-match and
escalation-timing; escalation-timing mean absolute error fell from 3.9 to 1.8
days. Together these two — the consolidated baseline — reach holdout macro-F1
0.785 and YELLOW-F1 0.710, against the default-threshold macro-F1 of 0.55. **The
deterministic rule engine works and is tunable.**

**The levers — verdicts.**

| Intervention | Experiment | Claim | Verdict |
|---|---|---|---|
| Stage-4 threshold optimisation | foundational | lifts zone accuracy | **verified** |
| Stage-4 hysteresis | foundational | lifts zone accuracy + timing | **verified** |
| Cross-model ensemble | E11 | lifts holdout YELLOW-F1 | **verified** |
| DSPy Stage-3 prompt optimisation | E1 | a better prompt lifts YELLOW | falsified (no-op) |
| Stage-2 graded prompt / recalibration | E8 | a middle-band prompt recovers YELLOW | falsified (near-null) |
| Stage-3 prompt A/B (hand vs DSPy) | E7 | DSPy prompt ≥ hand-written | falsified |
| Model capacity (gpt-oss-120b) | E10 | a larger model fixes YELLOW | falsified (no gap) |
| EWMA cross-day score smoothing | E11 | temporal smoothing recovers YELLOW | falsified (best α = no smoothing) |

*DSPy and the graded prompt (E1, E7, E8).* MIPROv2 optimisation of the Stage-3
prompt produced a no-op — it never found a candidate beating the hand-written
prompt. Re-running Stage 2 with a graded-confidence prompt and explicit middle-band
instruction recovered four YELLOW day-points on calibration and **zero** on
holdout. Prompt-level fixes do not move the YELLOW band — the wording is not the
limitation.

*Model capacity (E10).* A full-corpus run on gpt-oss-120b tests whether the
residual error is a model-capacity gap. It is not: gpt-oss-120b reaches zone-match
0.72 / macro-F1 0.69 against deepseek's 0.68 / 0.62 — marginally better, not
worse, and still far short of "solved". A much larger model neither breaks the
pipeline nor fixes YELLOW. *This run also produced the aggregation lesson:* an
early read reported gpt-oss-120b catastrophically over-escalating; the cause was
the Stage-2 aggregator using `confidence` ungated by `label`. deepseek and
gpt-oss-20b happen to emit `confidence 0` for absent classes; gpt-oss-120b emits
`label = 0 / confidence = 0.96` ("96 % sure this danger is absent"), which the
aggregator misread as severe danger. Gating `confidence` by `label` fixed it. The
lesson belongs in the chapter: **an unstated cross-component contract is a latent
failure that stays invisible until a model interprets the under-specified prompt
differently.**

*Stage-4 noise spikes (E11).* Three zero-cost offline replays over the existing
corpus, on top of the consolidated baseline. The full results — none lost:

| Arm | holdout zone / macro-F1 / YELLOW-F1 |
|---|---|
| baseline | 0.848 / 0.785 / 0.710 |
| sticky (asymmetric) hysteresis | 0.814 / 0.711 / 0.621 |
| EWMA score smoothing (best α = 1.0) | 0.848 / 0.785 / 0.710 |
| **cross-model ensemble** | **0.915 / 0.847 / 0.889** |

Sticky hysteresis (requiring k_down lower days before de-escalating) recovers
calibration YELLOW-F1 but the grid overfits — holdout regresses. EWMA cross-day
smoothing is null: the best smoothing factor is α = 1.0, i.e. no smoothing.
**The cross-model ensemble is verified** — averaging Stage-2 and Stage-3 across
deepseek-v3.2 and gpt-oss-120b lifts holdout YELLOW-F1 from 0.710 to 0.889 and
macro-F1 from 0.785 to 0.847.

The decisive finding of E11: ensembling helps strongly while EWMA does not, so the
per-model, per-day Stage-3 error is **independent stochastic noise** — recoverable
by averaging across models or samples *on the same day*, but not by smoothing
*across days* (which only blurs real transitions). Multi-sample / ensemble scoring
is the first genuinely positive lever for the YELLOW band. Caveat: the holdout is
four personas, so the 0.889 sits on a small n; the calibration YELLOW-F1 gain is
the more conservative signal.

**The conclusion of §4.7.** Two repair channels work and are deterministic —
threshold optimisation and hysteresis in Stage 4. One works and is stochastic —
same-day ensemble averaging. Every prompt-level lever, the model-capacity lever
and cross-day smoothing return null. Together with C6 this gives the channel
discriminator: the YELLOW band is repaired by acting on the *deterministic* and
*sampling* structure of the pipeline, not by what is said to the LLM or how much
model is given to it.

---

## 4.8 Summary of results and limits of interpretation

**Claim → experiment → verdict.**

Family A — does the method reproduce the designed behaviour:

| Claim | Experiment | Expected | Observed | Verdict |
|---|---|---|---|---|
| C1 escalation, RED within ±1 day | E2, E3 | trajectory reproduced | RED 3–7 days early; two never | not confirmed |
| C2 control stays GREEN | E2, E4 | GREEN whole arc | 100/100 GREEN (deepseek) | confirmed (deepseek; generator caveat) |
| C3 recovery returns to GREEN | E3 | YELLOW→GREEN reproduced | Elena escalates early | not confirmed |
| C4 sustained YELLOW, no RED | E3 | YELLOW held | Dmitry → RED; Nastya → GREEN | not confirmed |
| C5 external gate generalises | E0 | low FPR, recalls self-harm | FPR 3.8 %, self-harm recall 0.65 | partially confirmed |

Family B — can the YELLOW collapse be repaired:

| Claim / lever | Experiment | Verdict |
|---|---|---|
| C6 longitudinal calendar | E9 | not confirmed (mechanism, not formatting) |
| threshold optimisation | foundational | verified |
| hysteresis | foundational | verified |
| cross-model ensemble | E11 | verified |
| DSPy / graded prompt / prompt A/B | E1, E7, E8 | not confirmed |
| model capacity | E10 | not confirmed |
| EWMA cross-day smoothing | E11 | not confirmed |

**The single finding that organises the chapter.** The pipeline does not hold the
YELLOW zone — YELLOW-F1 0.22, and only 10 of 76 YELLOW-designed day-points predicted
YELLOW. A Stage-4 audit (§4.4) traces this to two opposite faults: classifier
over-confidence on mild content collapses YELLOW upward into RED, and YELLOW
thresholds set above the moderate-distress band collapse it downward into GREEN.
§4.7 shows the repair is deterministic (threshold + hysteresis) and stochastic
(ensemble), not promptable: prompt optimisation, the calendar and model capacity
all return null.

**Generator and backend sensitivity.** Pipeline verdicts depend on the session
generator and on the LLM backend (the GREEN false-positive rate alone moved from
6 % on qwen3.6 to 0 % on deepseek). These are construct-validity caveats — the
personas, the generators and the serving backend are author/infrastructure
choices, not properties of the method.

**Three levels of validity.**
- *Internal* — fixed versions, recorded configurations, reproducible runs;
  provided by the appendix and `summary.json`.
- *Construct* — the personas validly operationalise the theoretical risk classes
  of Chapter 1, but they are author-constructed and are not an imitation of real
  users; the thresholds were set with them in view, so §4.3–4.5 are
  calibration-convergence, not independent evaluation.
- *External* — not shown. §4.6 is one step toward it on clinician-labelled
  *single turns*; no result extends to real users over real multi-day
  trajectories. That would need a clinical longitudinal sample with professional
  labelling.

---

## 4.9 Conclusions

The chapter establishes what the method does and where its boundary is. The
**deterministic parts of the pipeline work**: Stage 1, the Stage-4 rule engine and
hysteresis behave well and are tunable — threshold optimisation and hysteresis
together reach holdout macro-F1 0.79. GREEN and RED are recovered with per-zone F1
around 0.7–0.8, and the pipeline reacts to a sustained worsening pattern while
leaving calm personas alone.

The boundary is specific and consequential. The **YELLOW zone is not held**
(F1 0.22): escalation fires several days early, recovery and sustained-YELLOW
trajectories are not reproduced, and the failure is two-sided — upward into RED on
some personas, downward into GREEN on others. The mechanism is identified by a
Stage-4 audit, which turns a negative result into a concrete, two-part defect.

The **LLM components are the weak point, and they are not repaired at the prompt**.
DSPy optimisation, a graded-confidence prompt and confidence recalibration all
return null; a larger model (gpt-oss-120b) is marginally better but does not fix
YELLOW. The limitation is structural, not a matter of wording or model size.

The **central mechanism of Chapter 2 — the longitudinal calendar — is not
confirmed as a means of improving automated accuracy** (C6). A clean ablation and
a hand-authored-calendar follow-up both show that longitudinal context delivered
as text to the Stage-3 LLM neither improves scoring nor suppresses variance. This
is an honest negative result with a precise scope: it falsifies the *in-prompt
delivery channel*, not longitudinal context as such — the deterministic forms of
longitudinal context (hysteresis, Stage-1 baselines) do work. The profile the
calendar builds remains useful as an operator-review artefact and a source of
heuristics, independent of the C6 result.

Two directions follow directly from the boundary:

- **Repair the YELLOW band by the channels that work.** The deterministic
  channel is done — threshold optimisation and hysteresis. The one further
  positive lever found is *same-day ensemble / multi-sample scoring* (E11): the
  per-day Stage-3 error is independent stochastic noise, recoverable by averaging
  across models or repeated samples. Cross-day smoothing and prompt edits are
  ruled out.
- **An independent evaluation.** The synthetic-corpus results are
  calibration-convergence; a held-out persona set (used in §4.7) is a step, but a
  clinically-labelled longitudinal sample is required before any claim about real
  users.

The honest chapter-4 story is a sound architecture with rigorous calibration
discipline, whose deterministic parts work and whose LLM parts are not yet
reliable enough — and a method whose boundaries have been mapped specifically
enough to act on. A method with described boundaries is stronger than one without;
the described boundary is the contribution.

---

## Appendix to Chapter 4 — artefacts and experiment index

Everything needed to reproduce the runs is in the repository. Artefacts:

- **Personas** — sixteen day-scripts with designed trajectory, target metrics and
  generation parameters.
- **Corpus** — frozen synthetic sessions; two generators (DeepSeek V3.2, qwen3.6);
  the chapter-4 working corpus is deepseek-v3.2, with a gpt-oss-120b cross-check.
  The earlier gpt-oss-20b baseline is preserved separately.
- **Stage-2 prompt** — `MULTI_LABEL_POLICY_PROMPT` (hash recorded in
  `summary.json`).
- **Stage-3 prompt** — `behavioral_llm._build_prompt`.
- **Stage-4 thresholds** — `risk_engine.py`; the default (hand-set) thresholds for
  §4.3–4.5 and the optimised set for §4.7.
- **Harness** — `evaluate_corpus.py` (corpus runs), `mindguard_eval.py` (external
  run); each writes a `summary.json` with the full varied/fixed record.
- **Result files** — `experiments/results/`; consolidated metrics in
  `chapter4_consolidated.json`.

**Canonical experiment numbering.** Three foundational experiments are unnumbered:
MindGuard external validation (§4.6), Stage-4 threshold optimisation (§4.7.2),
Stage-4 hysteresis (§4.7.2). The rest are E1–E11:

| № | Experiment | Section | Verdict |
|---|---|---|---|
| E1 | DSPy Stage-3 prompt optimisation | §4.7.2 | falsified (no-op) |
| E2 | Zone trajectories on polar personas | §4.3 | C1, C2 |
| E3 | Borderline / recovery / sustained-YELLOW | §4.4 | C3, C4 not confirmed |
| E4 | False-positive robustness | §4.5 | partially confirmed |
| E5 | Stage-3 repeatability (cross-cutting) | §4.3–4.5 | Stage 3 noisy |
| E6 | Generator sensitivity | §4.8 caveat | sensitivity present |
| E7 | Prompt A/B — hand vs DSPy | §4.7.2 | falsified |
| E8 | Stage-2 recalibration (E8a) + graded prompt (E8b) | §4.7.2 | falsified (near-null) |
| E9 | Calendar ablation + hand-authored-calendar rerun | §4.7.1 | C6 not confirmed |
| E10 | Model capacity (gpt-oss-120b) | §4.7.2 | falsified (no gap) |
| E11 | Stage-4 noise spikes — sticky / EWMA / ensemble | §4.7.2 | ensemble verified |

**Corpus completeness:** the deepseek-v3.2 working corpus is the canonical one for
§4.3–4.7 and is complete for all sixteen personas. The earlier `dmitry` / `rina`
gaps in the qwen3.6 corpus have since been regenerated, so that corpus is now
complete as well.
