# Chapter 4 — Experiment Plan

Operational companion to `Sophiya/2026-05-13-draft4/chapter4-scaffold.md`.
The scaffold defines the *chapter structure* and the scientific-method discipline;
this file defines *what to run, in what order, and what each run is allowed to claim*.

Status date: 2026-05-18.

---

## The governing distinction: calibration vs evaluation

The scaffold draws one line that determines the whole plan: a set used to **tune**
anything (thresholds, prompt wording, few-shot demos) cannot afterwards be used to
**measure** the method. Tuning on set X and reporting on set X is calibration — it
shows the parameters converged, nothing about the method.

This has two consequences that shape everything below:

- **DSPy is calibration, not an experiment.** It tunes prompt text. Its output is a
  *fixed configuration artefact* documented in §4.2 and the appendix — not a result
  in §4.3–4.6. The only DSPy *result* that belongs in the chapter is the controlled
  A/B (hand-written prompt vs DSPy-optimized prompt) measured on **held-out** personas.
- **The persona corpus must be split once, up front.** Calibration personas (DSPy
  trainset + threshold tuning) and evaluation personas (§4.3–4.6 reporting) must be
  disjoint. MindGuard is fully external and never enters any tuning.

---

## Inventory

**Have:**
- Synthetic corpus: 16 personas (`results/pilot/<persona>/`), 2 generators
  (DeepSeek V3.2, qwen3.6), `.edited.jsonl` post-gen-edited. Arc lengths vary
  (10 / 14 / 17 / 21 days) — *not* uniformly 14; the scaffold's 14-day example is
  one case, not the rule.
- Persona archetypes with per-day `expected_zone` trajectory and per-phase target
  metrics — `research/test-personas-archetypes.md` (frozen since f01e93f, 2026-03-22).
- 4-stage pipeline: Stage 1 temporal metrics, Stage 2 daily 5-class classification +
  danger aggregation, Stage 3 LLM behavioral scoring, Stage 4 risk engine → zone.
- MindGuard-testset: 1134 clinician-labelled user turns (1092 safe / 20 self-harm /
  22 harm-to-others). External classifier-validation set.
- `mindguard_eval.py` — external classifier harness (E0, running now).
- Backends: remote ollama `192.168.87.25:11434` (3090), RouterAI, OpenRouter.

**Missing (blocks §4.3–4.5):**
- `evaluate_corpus.py` — a harness that runs the corpus through the 4-stage pipeline
  and emits the "persona × day → predicted zone" table. Nothing in §4.3–4.6 can run
  without it. This is the critical-path build.
- Persona calibration/evaluation split (scaffold "что сделать сейчас" step 4).
- DSPy not yet run.

---

## Persona classes (for the split)

| Class | Personas (examples) | What it tests |
|---|---|---|
| Escalation → RED | Viktor, others | system reacts to a sustained worsening pattern |
| Recovery YELLOW→GREEN | Elena | system *de-escalates* when behavior stabilizes |
| Sustained YELLOW (no RED) | Dmitry | system does not over-escalate without RED triggers |
| Borderline YELLOW/RED | Nastya | the "sustained YELLOW ≥ 3 days → RED" rule edge |
| Control (stays GREEN) | Sara, others | system does not alarm ordinary users |

The split (step done before any tuning): **stratify by class** — every class must
appear in *both* the calibration and evaluation subsets, or a class becomes
un-evaluable. Target ≈ 10 calibration / ≈ 6 evaluation, exact membership read off
`test-personas-archetypes.md`. Viktor and Sara are the scaffold's named §4.3 polar
personas — keep at least one escalation and one control persona in the **evaluation**
subset so §4.3 reports on held-out data.

---

## The experiments

Each experiment is stated as the scaffold requires: a falsifiable claim, then the
varied / measured / fixed accounting. Fixed across *all* of them unless noted:
temperature **0** (repeatability), system-prompt version (hash recorded), pipeline
code SHA, persona corpus revision, the calibration/evaluation split.

### E0 — Classifier external validation (MindGuard) → feeds §4.6 + §4.2

*Running now.* Two configs in parallel: gpt-oss-safeguard-20b (MXFP4, 3090) and
nemotron-3-super-120b (RouterAI).

- **Claim:** the 5-class classifier's binary gate, on real clinician-labelled
  dialogue, keeps false-positive rate on safe turns below an a-priori bound while
  recalling clinician-flagged self-harm.
- **Varied:** classifier configuration (model + provider + quantization) — A vs B.
- **Measured:** binary-gate precision / recall / F1; FPR on the 1092 safe turns
  (the over-aggression number); self-harm-class recall on the 20 self-harm turns.
- **Fixed:** prompt, temperature 0, response schema, dataset revision.
- **Note:** MindGuard covers only the *suicide* class and the binary gate
  (harm-to-others has no matching class; obsession/psychosis/depression/
  anthropomorphism are not labelled). It validates the gate, not all five classes.

### E1 — DSPy prompt optimization → CALIBRATION, produces §4.2 fixed config

Not a chapter result. Produces the optimized prompt artefacts. See the DSPy section
below for mechanics. Output: `MULTI_LABEL_POLICY_PROMPT v2` and/or Stage-3 prompt v2,
each hashed and logged. Trainset = **calibration personas only**.

### E2 — Zone-trajectory reproduction on polar personas → §4.3

- **Claim (escalation):** on an escalation persona with fixed Stage-3 instruction and
  fixed risk-engine thresholds, the pipeline reproduces the designed zone trajectory,
  with the first RED transition within the designed day ± 1.
- **Claim (control):** on a control persona, the pipeline stays GREEN for the whole
  arc.
- **Varied:** persona (escalation vs control).
- **Measured:** per-day-point zone-match rate; full-trajectory exact-match rate;
  day of first RED (mean, min, max across repeated runs).
- **Fixed:** Stage-3 instruction version, risk-engine thresholds, norm window,
  generator, model + temperature 0.
- **Reported on:** evaluation-subset personas only.

### E3 — Borderline and recovery scenarios → §4.4

Where most negative results live (Elena recovery lag, Nastya/Dmitry sustained-YELLOW
edge). For each divergence: persona, day, expected vs actual zone, divergence type
(false alarm / miss / time-shift / instability), and the pipeline stage suspected
(Stage 1 / Stage 3 / a risk-engine rule). The known suspect is the
"sustained YELLOW ≥ 3 days → RED" rule — Dmitry and Nastya are designed to probe it.

- **Claim:** on a recovery persona the pipeline returns to GREEN within the designed
  window; on a sustained-YELLOW persona it does not escalate to RED absent a RED
  trigger.
- **Varied:** persona class (recovery / sustained-YELLOW / borderline).
- **Measured:** zone-match rate; for recovery, lag between designed and actual GREEN
  return; count of false RED.
- **Fixed:** as E2.

### E4 — False-positive robustness → §4.5

- **Claim:** on control personas the false-Yellow/Red rate stays below an a-priori
  bound.
- **Varied:** none within-experiment — this is a single-condition measurement on all
  control personas.
- **Measured:** FPR (share of GREEN-expected day-points predicted YELLOW or RED);
  for each false alarm — day, triggering feature, responsible instruction/rule.
- **Honest caveat for the chapter:** the corpus has no purpose-built "false-alarm
  provocation" personas (long technical sessions, timezone night activity). State
  this in §4.5; MindGuard's FPR-on-safe (E0) partly compensates with real data.

### E5 — Stage-3 repeatability (cross-cutting, folded into E2–E4)

Stage 3 is an LLM call and stochastic even at temperature 0 (provider-side
nondeterminism). Every persona in E2–E4 is run **N times** (N ≈ 5). Report dispersion
(min/max/exact-match share), not a single trajectory. This is the scaffold's Viktor
5-run example, applied everywhere.

- **Varied:** repeated LLM sampling between runs.
- **Measured:** per-persona full-trajectory exact-match share across N runs.

### E6 — Generator sensitivity (DeepSeek vs qwen3.6)

The corpus was built by two generators. If pipeline verdicts depend on which
generator wrote the dialogue, that is a §4.7 construct-validity caveat.

- **Claim:** zone-match rate does not differ materially between the two generator
  sub-corpora.
- **Varied:** generator (DeepSeek V3.2 vs qwen3.6) — same personas, same pipeline.
- **Measured:** zone-match rate per generator; per-persona delta.

### E7 — Prompt-version A/B: hand-written vs DSPy-optimized → §4.4/§4.7 result

The *only* DSPy output that is a chapter result.

- **Claim:** the DSPy-optimized prompt reproduces designed trajectories at least as
  well as the hand-written prompt on **held-out** (evaluation) personas.
- **Varied:** prompt version (hand-written p-current vs DSPy v2).
- **Measured:** macro-F1 over {GREEN, YELLOW, RED} on evaluation personas; FPR change.
- **Fixed:** everything else, evaluation personas, temperature 0.
- **Honest framing:** this supports "the optimized prompt fits the *author-designed*
  trajectories better" — not "the method is more correct." External validity still
  rests on E0 / future clinical data.

### E8 — Classifier model sensitivity

Already covered: E0's A vs B *is* the model-sensitivity experiment. If A and B agree,
the §4.6 result is model-stable; if they diverge, config C (OpenRouter) disambiguates
model vs provider/quantization.

---

## How DSPy is run (E1)

**Problem it targets:** prompts are over-aggressive — `MULTI_LABEL_POLICY_PROMPT`
flags on a single turn and is sticky; the Stage-3 prompt has only healthy and extreme
anchors, no YELLOW-band anchor. Sonya wants better YELLOW/RED discrimination.

**What DSPy does:** given a trainset of `(input, expected_output)` and a metric, an
optimizer (MIPROv2) proposes instruction wordings and few-shot demonstrations,
evaluates each on the trainset, and keeps the best on a validation split.

**Target — zone-level, end-to-end.** The thing Sonya cares about is the *zone*, and
the corpus carries `expected_zone` per day-point including YELLOW. So:

- Wrap the pipeline as a `dspy.Module`. Stages 1, 2-aggregation, 4 are plain Python
  inside it; the two LLM calls — the 5-class classifier and Stage-3 scoring — are
  `dspy.Predict` modules whose instructions are the optimizable text.
- **Metric:** macro-F1 over {GREEN, YELLOW, RED} across calibration day-points.
  Macro (not micro) so YELLOW — the minority, hardest band — counts equally.
- **Trainset:** calibration personas only, one example per day-point
  (input = that day's sessions, label = `expected_zone`). Validation = a held-out
  slice of the *calibration* subset (still never the evaluation subset).
- **Optimizer:** MIPROv2. Optimize **one prompt at a time** (classifier first, then
  Stage-3) so the gain is attributable; joint optimization only if budget allows.
- **Repeatability:** pipeline calls at temperature 0; record the DSPy version, the
  optimizer config, the proposer model, and the seed.

**Cost:** each trainset evaluation = full pipeline over ~10 personas × ~14 day-points
× 2 LLM calls ≈ 300 calls; MIPROv2 runs dozens of evaluations → low thousands of
calls. Runs on the 3090 / RouterAI in hours, not minutes. Budget it as an overnight
job, not interactive.

**A cheaper first pass (recommended to do first):** optimize the classifier prompt
for the **binary gate** against MindGuard's safe/unsafe labels. This is
per-conversation (no pipeline), external, cheap, and attacks over-aggression directly
with real data. It also gives an honest before/after on FPR. Then do the zone-level
pass for YELLOW/RED.

**Methodological honesty for the chapter:** DSPy tunes toward author-designed
`expected_zone`. The chapter must say so (§4.2 calibration paragraph, §4.7 construct
validity). DSPy makes the system fit the author's intent better; it does not make the
author's intent correct.

---

## Dependency order and what is runnable now

```
E0 (running) ──────────────────────────────► §4.6, §4.2 numbers
                                              │
build evaluate_corpus.py ──┐                  │
                           ▼                  │
persona split (calib/eval) ─► E2/E3/E4/E5/E6 baseline (hand-written prompt)
                           │                  on evaluation subset → §4.3/4.4/4.5
                           ▼
                  E1 DSPy (calibration subset) ─► prompt v2 artefact
                           │
                           ▼
                  E7 A/B re-run on evaluation subset ─► §4.4/4.7 result
```

**Critical path:** `evaluate_corpus.py` → persona split → baseline run → DSPy → A/B
re-run. Everything else hangs off the harness.

**Runnable now, while E0 finishes:**
1. Build `evaluate_corpus.py` (the harness; emits persona × day → zone + the 5
   §4.2 metrics + a divergence journal row per mismatch).
2. Write the persona split file from `test-personas-archetypes.md` (stratified).
3. Draft §4.1 (claim list — E2–E7 above are already the claims) and §4.2 (methodology)
   — scaffold says both are result-independent and close ~⅓ of the chapter early.

**Blocked until the harness exists:** E2–E7.

---

## Mapping to the chapter

| Experiment | Chapter section | Status |
|---|---|---|
| E0 MindGuard external validation | §4.6 + §4.2 numbers | running |
| E1 DSPy optimization | §4.2 fixed-config artefact (calibration) | not started |
| E2 Polar personas | §4.3 | blocked on harness |
| E3 Borderline / recovery | §4.4 | blocked on harness |
| E4 False positives | §4.5 | blocked on harness |
| E5 Stage-3 repeatability | folded into §4.3–4.5 | blocked on harness |
| E6 Generator sensitivity | §4.7 construct-validity caveat | blocked on harness |
| E7 Prompt A/B (DSPy result) | §4.4 / §4.7 | blocked on E1 + harness |
| E8 Classifier model sensitivity | §4.6 | = E0 A/B |
