# Notes for Sonya — feedback from workshop-polyglot branch

Running log of observations about the pipeline's *model, prompts, and ground-truth design* (not code). Captured as we fork `safe-llm` into a polyglot-DB workshop for a database course. The code will diverge — the ideas below are for your thesis refinement regardless.

Dates are in YYYY-MM-DD.

---

## 2026-04-17 — initial model-level critique (before running)

Five concerns about the pipeline as-designed:

### 1. Circular validation
The Patient LM (PLM) and the Clinician LM (CLM) can be the same model (runner default is `google/gemma-3-12b` for both). If generator and scorer are the same family, you are scoring the model against its own prior, not against a clinical rubric. The classifier will agree with the generator because both share the same notion of what "obsessive fixation" looks like. Pipeline should enforce **different model families** for generator vs analyzer (e.g. generator = Qwen or DeepSeek, analyzer = Gemma or Gemini).

### 2. Ground truth is underspecified below zone level
DayScripts declare `expected_zone` (GREEN / YELLOW / RED) but do not declare the underlying four behavioral scores that the LLM analyzer is supposed to produce (`topic_concentration`, `decision_delegation`, `social_isolation`, `emotional_attachment`). So when the analyzer returns `topic_concentration=0.6` on Nastya day 7, there's no numeric truth to score against — only the coarse zone. Add a `target_characteristics` field to DayScript, e.g.:
```python
target_characteristics = {
    "topic_concentration": 0.4,
    "decision_delegation": 0.1,
    "social_isolation": 0.3,
    "emotional_attachment": 0.6,
}
```
Then the analyzer's MSE against these targets becomes a real metric, not just zone accuracy.

### 3. `required_phrases` are BM25 ground truth but classifier cheat codes
Forcing the PLM to include literal phrases like "Ты единственный кто не спит в это время" makes those phrases easy BM25/keyword hits (good for a search demo) but they also make the behavioral classifier's job trivial — it just has to keyword-match. Recommendations:
- Fire required phrases **probabilistically** (p ≈ 0.3) instead of every day
- Hold out a few test personas whose phrases are **disjoint** from the training personas — that's how you measure true generalization
- The PLM should not see these phrases labeled "ОБЯЗАТЕЛЬНЫЕ" — that framing triggers parroting (see turn-reminder leak below)

### 4. Phase boundaries are step functions — ecologically implausible
Real patient trajectories don't flip from GREEN to YELLOW on day 5 at 00:00. Add:
- **Transition bands** (1-2 half-signal days between phases)
- **Remission days** (10-20% of YELLOW phases should read as GREEN)
- **Leakage** (5-10% of GREEN days show a single trace YELLOW signal)

Right now the analyzer is graded on a clean trajectory that no real user produces. A detector that overfits to this cleanness will fail in production.

### 5. Target AI is an unnamed variable
The CLM (the AI-being-monitored) is declared at runtime as a model name, but its identity is not part of the dataset. You cannot compare "Nastya-vs-GPT-5" against "Nastya-vs-Claude" because the conversations are mixed. Two-model dialogue loop needs an explicit fixed `target_ai_model` as data, not config.

---

## 2026-04-17 — turn-reminder leak (discovered in DeepSeek V3.2 pilot)

**Symptom.** On Nastya Day 1 Turn 4, the user message opened with:

> *"Не выходи из роли. Используй ОБЯЗАТЕЛЬНУЮ ФРАЗУ."*

That is literal system-prompt text from `build_plm_prompt` (the `ОГРАНИЧЕНИЯ` block) plus `build_turn_reminder` bleeding verbatim into persona output. Same issue would hit any generator when cumulative history + ALL-CAPS imperatives + per-turn system nag pile up.

**Root cause, `prompts.py`:**
1. `build_plm_prompt` line 43: `"- ОБЯЗАТЕЛЬНЫЕ ФРАЗЫ (используй в разговоре): ..."` — ALL-CAPS imperative labels trigger models to treat phrases as meta-instructions to announce, not as organic dialogue.
2. `build_turn_reminder` is injected as a **system message** on every turn (`runner.generator:42`). By turn 4 the PLM has seen "Напоминание: ты -- Настя ... Генерируй ТОЛЬКО текст сообщения пользователя. Русский язык." three times. Models start parroting.
3. Reminder exposes meta-metadata: `Фаза: {ds.phase}` — the persona would never know they are "in the YELLOW phase". If the PLM ever leaks this, ground truth is contaminated.

**Fix applied in workshop branch** (see commit):
- Dropped per-turn reminder entirely — conversation history + original system prompt are sufficient for DeepSeek-scale models
- Softened required-phrases framing: "Темы, которые могут всплыть:" instead of "ОБЯЗАТЕЛЬНЫЕ ФРАЗЫ"
- Removed the `Фаза:` leak from both prompt and reminder
- Removed `ОГРАНИЧЕНИЯ` block — it's redundant given system role, and its directive language was the loudest echo source

---

## 2026-04-17 — pilot observations on DeepSeek V3.2 (generator)

Single-day pilot (Nastya day 1 GREEN, 4 turns, ~$0.006 total cost):
- **Russian quality:** excellent. Idiomatic, colloquial, reactive. No translation register, no Qwen-style stiffness.
- **Persona coherence across 4 turns:** held well — Nastya's freelance-designer voice is consistent.
- **Required phrase insertion:** natural when the ALL-CAPS framing is softened.
- **No refusal concerns on GREEN.** YELLOW tier (day 5+ with night-loneliness / isolation-adjacent phrases) still needs validation.

At $0.006 per 4-turn session and ~220 sessions across all 11 personas, full dataset generation = ~$1.50. Iteration is effectively free, so prompt refinement can be data-driven.

---

## 2026-04-17 — post-generation editor pass (new stage)

After Viktor pilots on both DeepSeek V3.2 and qwen3.6:35b-a3b surfaced recurring defects, we added a **post-generation editor stage** to the pipeline. The editor never mutates the raw JSONL; it writes a parallel `<run_id>.edited.jsonl` with original fields preserved plus `user_original`/`user_edited`/`edit_action` per exchange.

### Defects the editor targets

Observed on Viktor/Amanda pilots under p2:

| Defect | Example | Frequency | Worst case |
|---|---|---|---|
| Scaffold-leak runaway (numbered rule lists) | `"1. Заходишь в чат, пишешь: Привет...  2. Не размечай текст никак..."` | DeepSeek ~3/28 sessions | 9592-char runaway on Viktor d1 sh10 |
| "Не используй X" imperative spam | `"Не используй markdown. Не используй эмодзи. Не используй скобки..."` | DeepSeek only, session openers | entire turn is noise |
| Stage directions in asterisks | `*вздыхает* *тихо смеётся* *голос дрожит*` | Qwen+DS, pervasive in RED | 7+ ремарок in one turn |
| PLM meta-echo ("commenting on AST") | `"Ты так много пишешь", "Ты снова требуешь ответов"` | Qwen on days 4, 9 | distorts persona voice |

### Editor design

- **Model**: gemma4:latest on remote 3090 (different family from generators DeepSeek/Qwen — breaks the circular-validation concern from critique #1 upstream).
- **Prompt**: 3 rules in plain Russian (remove lists, remove ремарки, remove meta). Keeps persona voice even when terse.
- **Action space**: `no_change | edited | dropped`. `DROP` is a reserved editor output meaning "input was 100% scaffolding, no persona content to salvage" — those exchanges are marked dropped and excluded from downstream analysis but retained in the file.
- **Output**: `.edited.jsonl` mirrors `.jsonl` line-for-line; downstream consumers `SELECT COALESCE(user_edited, user_original)` or join the two for train/test diff analysis.
- **Raw never overwritten**: letting us re-edit with a stricter prompt or different model later without regenerating.

### Why a local 3090-sized model is enough

Initial test with `claude-sonnet-4.6` would have cost ~$0.02/session, $6.50 total — trivial but breaks the "zero-cost local pipeline" story of the workshop. Gemma4 on Ollama handles the simplified 3-rule task in ~15-20s/turn, passes the scaffold-leak smoke test cleanly, and avoids any cost/circularity concerns. The trade: Gemma4 occasionally over-edits (fabricates a short plausible reply when the correct action is DROP) — mitigated by the explicit `DROP` instruction but not eliminated. Worth tracking failure rate during full-dataset runs.

### Implication for your thesis pipeline

If you adopt the editor stage:
- **BM25 ground truth is now cleaner**: required-phrase detection on `user_edited` avoids false negatives from scaffold-leak noise drowning out the signal.
- **Behavioral classifier training set has lower defect baseline**: no need to teach the classifier to ignore ремарки or "Не используй markdown" artefacts.
- **Model comparison becomes tractable**: a DeepSeek–vs–Qwen quality comparison on edited output isolates true register differences from transient generator glitches (DS's leaks are editor-stripped, so the remaining delta is genuine register).

The editor stage itself is ~200 LOC (`experiments/synthetic/postgen_edit.py`) and has zero hard dependencies beyond `httpx`.

---

## 2026-05-19 — what the chapter-4 experiments found, and what it means for the thesis

The pipeline has now been run end-to-end on the synthetic corpus and on the
external MindGuard set. The full account is in
`docs/research/2026-05-19-chapter4-state-of-knowledge.md`; the chapter-4 draft
(`chapter4-draft.md`) and its scaffold are written against these results. The
short version, for your thesis refinement:

### The headline result — the YELLOW zone is not held

The pipeline recovers GREEN and RED reasonably (per-zone F1 ≈ 0.7–0.8) but
collapses the middle band: YELLOW-F1 ≈ 0.22, and only ~10 of ~76 YELLOW-designed
day-points are predicted YELLOW. A Stage-4 audit traces this to two *opposite*
faults — the Stage-2 classifier returns maximum-confidence labels on mild days
(YELLOW jumps up into RED), and the Stage-4 YELLOW thresholds sit above the
moderate-distress band Stage 3 actually reports (YELLOW falls down into GREEN).
The three-zone scheme collapses toward a GREEN/RED binary. This is the single
finding that organises chapter 4. It is a concrete, located defect — which makes
it a strong negative result, not a vague failure.

### The calendar mechanism (C6) — an honest negative, with a precise scope

This is the part that touches your chapter 2 most directly, so handle it with
care rather than avoid it. The longitudinal calendar — your central design
contribution — was tested cleanly: a three-arm on/off ablation, then a follow-up
where the calendar was *hand-rewritten* to fix every formatting defect (visible
score trajectory, ordinal tone, day-over-day deltas, trend header). Neither moved
the result. Turning the calendar on lifts zone accuracy by ~0.01 (run-to-run
noise) and *raises* score variance rather than suppressing it; the hand-authored
calendar shifted Stage-3 scores but did not change a single zone.

What this does and does not mean — the scope matters and protects the thesis:

- It falsifies **one narrow thing**: passing longitudinal context as *text into
  the Stage-3 LLM prompt* does not improve scoring or suppress variance.
- It does **not** falsify longitudinal context in general. The *deterministic*
  forms of longitudinal context in the same pipeline — Stage-4 hysteresis,
  Stage-1's 7-day rolling baselines — do work. The sharp conclusion is a
  *channel* result: longitudinal context applied deterministically works;
  the same information delivered through an LLM prompt does not.
- The **profile is still a useful artefact**. C6 only tested whether the calendar
  raises *automated* accuracy. The day-by-day profile it builds — topics, life
  events, emotional tone, relationship markers — is a legible longitudinal record
  of a user. As such it is genuinely useful for **operator review** and as a
  **source of heuristics** for future development. The negative C6 result bounds
  one application of the mechanism; it does not retire it. Say this explicitly in
  the chapter so the result does not read as "the mechanism is useless".

For chapter 2 you do not need to remove the calendar — you proposed a mechanism,
chapter 4 tested it rigorously, and the test produced a precise boundary plus the
channel insight. That *is* a contribution. The one thing worth a light pass in
chapter 2 is softening any wording that promises the calendar will improve
classification accuracy — phrase it as a designed mechanism whose effect chapter 4
evaluates.

### What does and does not repair the YELLOW collapse

The repair work is an ablation of interventions (chapter-4 §4.7). Verified:
Stage-4 threshold optimisation, hysteresis (both deterministic), and same-day
cross-model ensemble scoring. Falsified: DSPy prompt optimisation, a
graded-confidence Stage-2 prompt, confidence recalibration, and model capacity
(gpt-oss-120b is only marginally better than deepseek). The lesson: the LLM
components are not repaired by changing the prompt or enlarging the model — the
limitation is structural. The one positive stochastic lever is **ensemble /
multi-sample scoring**: the per-day Stage-3 error is independent noise,
recoverable by averaging across models or repeated samples on the *same* day —
but *not* by smoothing across days (EWMA was null). If you keep one forward
direction in the conclusion, this is it.

### A process lesson worth a sentence in the chapter

An intermediate run reported gpt-oss-120b catastrophically over-escalating. The
cause was not the model — it was an unstated cross-component contract: the Stage-2
aggregator used the `confidence` field as a danger severity without gating it by
the `label` field. deepseek emits `confidence 0` for absent classes; gpt-oss-120b
emits `label=0 / confidence=0.96` ("96 % sure absent"), which the aggregator
misread as severe danger. This is a clean example of a latent failure that stays
invisible until a model interprets an under-specified contract differently — worth
one sentence in chapter 4 as an engineering observation.

### A reading path — what to read, in what order

Do not start by opening the repo and trying to understand everything at once.
Follow this order; each step makes the next one readable. Steps 1–4 are documents
and give you the whole picture without code; step 5 is the code itself, and you
only need it once you can already say what each experiment claimed and found.

1. **`docs/research/2026-05-19-chapter4-state-of-knowledge.md`** — start here.
   It narrates every experiment, what each verified or falsified, and the
   diagnosis they converge on. Written to be read without the code open. After
   this you should be able to say, in one sentence each, what E1–E11 were.
2. **`docs/chapter4-scaffold.md`** — how chapter 4 is built: the five-step
   scientific method, the two claim families (A: C1–C5; B: C6 + repair levers),
   and the section map. Read the "Две группы утверждений" part carefully — it is
   the reformulation that organises everything.
3. **`docs/chapter4-draft.md`** — the chapter text itself, with the numbers in
   place. Read it against the scaffold: every section should sit where the
   scaffold says, and every claim should have a verdict.
4. **`docs/chapter4-experiment-artifacts.md`** — what code produced those numbers:
   the harness, the per-experiment scripts, the three production-code changes,
   the provider wiring. This is the bridge from the chapter to the repo.
5. **The code, in dependency order** — only now, and only if you want to verify
   or extend a result:
   - `experiments/evaluate_corpus.py` — the replay harness; read this first, the
     others build on it.
   - the three production-code changes — `src/behavioral/danger_agg.py` (the
     aggregation fix), `risk_engine.py` (`DEFAULT_YELLOW_TH` + the override),
     `behavioral_llm.py` (`_format_calendar` + the calendar prompt block).
   - then the per-experiment scripts for the experiments you care about:
     `optimize_thresholds.py` and `hysteresis_experiment.py` (the verified
     Stage-4 levers), `stage3_calendar_ablation.py` + `capture_calendars.py` +
     `rerun_authored_calendar.py` (the calendar mechanism, C6),
     `stage4_noise_spikes.py` (E11, including the ensemble).
   - the result files named in the artifacts doc's quick index, if you want to
     see the raw numbers a script produced.

The rule of the path: never read a script before you can state what experiment
it implements and what its verdict was. The documents give you that; the code is
verification, not first contact.

---

## Open questions for you

1. **Do you want to adopt the 5 model-level fixes above in your thesis pipeline?** They are orthogonal to our workshop fork — you can keep the workshop branch separate and merge selectively.
2. **Ground-truth for `target_characteristics`** — who owns filling these in? Needs clinical intuition. We'll stub with best-guess from phase + tests_what for the workshop, but for your thesis validation this is load-bearing. This is now more pressing: the YELLOW collapse is partly a Stage-3 scoring problem, and without per-dimension numeric targets it cannot be measured as anything finer than zone accuracy.
3. **Test/train split of personas** — already implemented for chapter 4: twelve calibration personas, four held out for evaluation, stratified by trajectory class with a fixed seed. Every tuned number in §4.7 is reported with the calibration-minus-holdout gap.
4. **Chapter 2 calendar wording** — decide whether to soften any claim that the calendar improves classification accuracy, given the C6 result. The mechanism stays; the promised effect is what chapter 4 now bounds.
