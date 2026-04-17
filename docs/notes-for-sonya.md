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

## Open questions for you

1. **Do you want to adopt the 5 model-level fixes above in your thesis pipeline?** They are orthogonal to our workshop fork — you can keep the workshop branch separate and merge selectively.
2. **Ground-truth for `target_characteristics`** — who owns filling these in? Needs clinical intuition. We'll stub with best-guess from phase + tests_what for the workshop, but for your thesis validation this is load-bearing.
3. **Test/train split of personas** — which personas should be held out? Candidates: Dmitry, Rina, Joseph — personas whose required_phrases don't overlap lexically with the others.
