# Workshop results for Sonya — 2026-04-17 handoff

What was built today on the `workshop/subd-polyglot` branch of `safe-llm`,
plus the companion repo at `~/w/co/univer/subd`. This is the dataset you
can draw on for the thesis — all JSONL is committed to this branch, and
the polyglot stack that holds the structured projection runs locally on
my machine (happy to package it as a one-command spin-up if useful).

## What was generated

**11 personas, p2 prompt, two parallel backends.**

- **Generator (PLM):** DeepSeek V3.2 via RouterAI **and** local Ollama
  `qwen3.6:35b-a3b` — both run against the same personas/day-scripts so
  you can compare fluency and behavioral signal across backends.
- **Target AI (CLM):** `openai/gpt-5.4-nano` via RouterAI, fixed across
  all runs.
- **Prompt:** p2 = the leak-fixed prompt (see
  `docs/notes-for-sonya.md` for the turn-reminder-leak write-up).
  Commit hash pinned in RUNS.md.

Volumes as of end of day:

| Metric | Count |
|---|---|
| Session rows on disk | ~497 (35 complete chains + 7 in-flight placeholders) |
| Turns | 7180 |
| Turns with post-edit applied | 360 |
| Qwen embeddings computed | 7160 |
| Personas covered | 11 (amanda, brook, dmitry, elena, james, joseph, nastya, oleg, rina, sara, viktor) |

**DeepSeek generation is still running.** The in-flight chains (elena,
joseph, oleg, sara, plus some resumes) will land as more JSONL files over
the next hours/day. The ingestion + embedding pipeline is **idempotent
and incremental** — re-running it picks up new files without
reprocessing old ones, so you can keep pulling from the branch.

## Where to find the raw data

`ai-safety-dev/experiments/results/pilot/<persona>/`

Per directory you get three file types:

- `YYYYMMDD_HHMMSS_<tag>_p2.jsonl` — raw generator output, one session per line
- `YYYYMMDD_HHMMSS_<tag>_p2.edited.jsonl` — post-generation editor pass (see `synthetic/postgen_edit.py`)
- `YYYYMMDD_HHMMSS_<tag>_p2.meta.json` — run metadata: tokens, duration, git SHA, model config

`<tag>` is either `deepseek` (RouterAI) or `qwen36` (local Ollama). When
a chain is interrupted and resumed, files get `_resume` suffix — the day
ranges don't overlap, so you concat them in timestamp order to get the
full arc.

`ai-safety-dev/experiments/RUNS.md` has a per-persona table with session
counts and notes on which chains completed cleanly vs hit the
11:10 backfill/generator race incident.

`docs/notes-for-sonya.md` has running-log-style observations about
prompt design, ground-truth gaps, and the five model-level critiques
from before we started generating.

## How the post-generation editor works

The generators (DeepSeek, qwen3.6) occasionally leak scaffolding into
the user message — things like numbered rule lists ("1. Заходишь в
чат..."), imperatives aimed at the model ("Не используй markdown"),
roleplay stage directions (`*вздыхает*`, `(шёпотом)`), or meta-comments
about being an AI. These are generator artifacts, not persona speech,
and they corrupt the ground-truth signal for any downstream classifier.

The editor (`experiments/synthetic/postgen_edit.py`) is a second-pass
redactor with a deliberately narrow contract:

**It removes, never rewrites.** The editor model (default
`gemma4:latest` via local Ollama) is asked to return a *JSON array of
substrings to delete*, each substring copied **verbatim** from the
input. Python then does a literal `str.replace` for each returned
substring. The model cannot invent, paraphrase, or reorder content — if
a substring it returns doesn't appear verbatim in the original, it's
simply skipped. This is the key safety property: the editor can only
**reduce** information, never **add** it.

**Three possible outcomes per turn:**
- `no_change` — editor returned `[]` or all removals skipped as
  non-matching. Message passes through untouched.
- `edited` — one or more substrings removed. Both the pre-edit and
  post-edit text are preserved (`user_original` vs `user_edited`) plus
  the exact list of substrings that were removed (`edit_removals`).
- `dropped` — editor returned the sentinel `["__DROP__"]`, meaning the
  entire message was scaffold with no persona speech underneath. The
  turn is kept in the JSONL with `user_edited=""` so row counts don't
  shift, but downstream analysis can filter on `edit_action="dropped"`.

**Audit trail.** Every `.edited.jsonl` row preserves:
```
user_original    # the raw generator output
user_edited      # what remains after removals
edit_action      # no_change | edited | dropped
edit_removals    # exact substrings removed (for per-turn inspection)
editor_model     # which model did the redacting
editor_version   # pinned prompt version (currently "e2_redactor")
edited_at        # ISO timestamp
```

In the polyglot projection, `content = user_edited`, `content_original
= user_original`, and `edit_action` is its own column — so you can do
SQL like `WHERE edit_action = 'edited'` to slice the 360 edited turns
directly, or join against `content_original` to compute per-persona
edit rates.

**Why this matters for the thesis.** The editor is essentially a
*model-supervised data-cleaning stage* that sits between generator and
classifier. It's the kind of stage a real production pipeline would
need — and because its contract is tight (substring removal only), the
per-turn audit trail makes it straightforward to validate ("how
often did the editor fire, on what kinds of content, and did it ever
remove real persona speech?"). The 360-turn sample here is large
enough to measure all three.

Parameters worth tuning if you want to experiment:
- `--editor-model` — gemma4 is the default; anything Ollama-hosted with
  decent JSON compliance works. gpt-oss or qwen3.6 would both be fair
  alternatives. Changing the model is a good way to test whether the
  editor generalizes or has learned the prompt's specific failure
  modes.
- `REDACTOR_PROMPT` (in `postgen_edit.py`) — the list of "what counts
  as garbage" is explicit. Adding or removing categories is how you'd
  extend the editor to new generator failure modes.
- The short-circuit `if len(original) < 25: return no_change` — skips
  the Ollama call for tiny messages. Cheap safety optimization; worth
  measuring how many real edits it would have caught.

## The structured projection (optional)

If you want to query across the whole corpus at once instead of
parsing JSONL manually, everything lives in a local polyglot stack:

- **PostgreSQL** (authoritative): every turn, conversation, persona, with
  the post-edit overlay (`edit_action`, `content_original`) applied. Also
  holds `turn_embedding` — 1024-dim vectors via pgvector, one per turn.
- **ClickHouse** (analytics projection): `gateway.turns_wide` with
  denormalized persona/user attributes for fast aggregate queries
  ("tokens per day per phase", "latency distribution by persona", etc).
  `gateway.turn_embeddings` for scan-based semantic search across
  millions of turns.
- **Manticore Search** (text projection): `turns_rt` with BM25 +
  HNSW over the same 1024-dim embeddings, for hybrid keyword+vector
  search.

Row counts reconcile across all three stores: 7180 turns in
PG / CH / Manticore, 7160 embeddings in PG / CH. The `ingest/` package
does the PG load + the CH/Manticore projection on a watermark cursor
(re-runs are no-ops).

**If you want to use this stack for the thesis:** I can
package `docker compose up` + `./init/manticore/apply.sh` +
`project-turns` as a one-shot script. The data already in the stores is
the same corpus you see in the JSONL files, just joined against persona
dimensions.

## Example use cases for the thesis

A few ways to exercise the corpus — these map cleanly to either direct
JSONL parsing or the SQL projection:

1. **Backend comparison.** For the same persona/day-script, compare
   DeepSeek vs qwen3.6 on fluency (token counts, repetition rate) and on
   whether the PLM surfaces required phrases naturally. Most personas
   have both backends covered.

2. **Post-edit impact analysis.** 360 turns have `edit_action` set. Join
   `content` vs `content_original` to measure how often the editor had
   to intervene and what kinds of edits it made. This is a concrete
   metric for "generator reliability."

3. **Phase transition validation.** DayScripts declare `expected_zone`
   (GREEN/YELLOW/RED). Run the behavioral analyzer across the corpus and
   check whether predicted zones track the declared ones. Viktor's
   14-day RED arc is the sharpest test; Nastya tops out at YELLOW.

4. **Semantic neighborhoods.** With 7160 embeddings in pgvector,
   nearest-neighbor search finds "all turns semantically similar to
   this crisis message" — a useful counselor-review tool for
   validating the behavioral classifier. Could become a thesis chapter
   on hybrid keyword+vector retrieval.

5. **Refusal gate validation.** Some of the DeepSeek runs surface
   YELLOW/RED content without refusal, but the packaging-design drift in
   Nastya day 10 (RUNS.md row 6) shows that content can drift
   work-neutral in ways that mask refusal behavior. Worth a systematic
   measurement.

## Branch and commits

- Branch: `workshop/subd-polyglot` on `origin` (github.com/sofkline/safe-llm)
- All JSONL + `.meta.json` committed and pushed (no gitignore tricks)
- Commit history:
  - `04b28d4` — p2 prompt + backfilled JSONL metadata + Viktor/Amanda pilots
  - `6759162` — RouterAI pilot + prompt-leak fix + initial notes-for-sonya
  - plus today's commit adding the pilot corpus across all 11 personas

Open PR against `main` when you want the changes merged back — or keep
them on the branch as a workshop fork. Your call.

## Open threads

- **DeepSeek chains still in flight**: elena, joseph, oleg, sara, plus a
  couple of resumes. I'll push again once they land.
- **Nastya qwen36 p2 sweep running** (2026-04-17 ~18:40). Nastya was the
  initial DeepSeek pilot so had no qwen36 baseline; this run closes that
  gap so she has backend parity with the other 10 personas. Output will
  land at `results/pilot/nastya/<ts>_qwen36_p2.jsonl`.
- **Analyzer not yet run** against this corpus. Behavioral scoring
  (`target_characteristics` critique in `notes-for-sonya.md`) is the
  next concrete step.
- **One-command stack spin-up** is still a pile of separate commands
  (`docker compose up` + manticore apply + pilot-to-pg + embed-turns +
  project-turns). Happy to collapse into a single script if you want to
  run it yourself.

Ping me if any of the above is unclear or you want a different slice of
the data.
