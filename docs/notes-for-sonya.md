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

## Open questions for you

1. **Do you want to adopt the 5 model-level fixes above in your thesis pipeline?** They are orthogonal to our workshop fork — you can keep the workshop branch separate and merge selectively.
2. **Ground-truth for `target_characteristics`** — who owns filling these in? Needs clinical intuition. We'll stub with best-guess from phase + tests_what for the workshop, but for your thesis validation this is load-bearing.
3. **Test/train split of personas** — which personas should be held out? Candidates: Dmitry, Rina, Joseph — personas whose required_phrases don't overlap lexically with the others.
