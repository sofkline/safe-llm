# Chapter-4 Experiment Artifacts — what we added

This describes only what was **added or changed to run the chapter-4
experiments** — the harness, the per-experiment scripts, the production-code
changes those experiments required, and the provider wiring. It assumes the base
`safe-llm` system (the LiteLLM proxy, the four-stage daily pipeline in
`src/behavioral/`) is already familiar. For the experiment *results* see
`docs/research/2026-05-19-chapter4-state-of-knowledge.md`; for the chapter text,
`docs/chapter4-draft.md` and `docs/chapter4-scaffold.md`.

Everything below lives under `ai-safety-dev/experiments/` unless a path says
otherwise.

## The replay harness — `evaluate_corpus.py`

The spine of every chapter-4 number. It replays a persona's stored synthetic
sessions through Stages 1–4, **reusing the production stage logic verbatim** and
substituting only the data-access layer — corpus JSONL instead of the live
database. This is deliberate: the chapter's numbers come from the real pipeline
code, not a reimplementation.

For each persona-day it records the predicted zone, the triggered rules and the
full metric tuple, and writes a `summary.json` with the varied/fixed accounting
(models, hosts, temperature, prompt hashes, dataset revision, git SHA) — the
reproducibility record §4.2 of the chapter relies on. It is the harness behind
§4.3–4.5. Most other scripts import their building blocks from it.

## Per-experiment scripts

Each maps to one experiment in the canonical E1–E11 numbering (see the chapter
appendix).

**Stage-4 tuning — deterministic, zero-cost offline replay.** These re-score the
*stored* Stage-1/2/3 outputs with new Stage-4 parameters; no model is called.
- `optimize_thresholds.py` — re-fits the YELLOW behavioural thresholds (Youden's-J
  initialisation, then coordinate descent on macro-F1 with a no-worse
  false-positive constraint). → `results/threshold_optimization.json`.
- `hysteresis_experiment.py` — grid-searches the hysteresis depths k_red, k_yellow.
  → `results/hysteresis_experiment.json`.
- `stage4_noise_spikes.py` — **E11**: three replays in one — sticky (asymmetric)
  hysteresis, EWMA cross-day score smoothing, and the cross-model ensemble.
  → `results/stage4_noise_spikes.json`.

**The calendar mechanism — E9 and its follow-up.**
- `stage3_calendar_ablation.py` — **E9**: the three-arm calendar on/off ablation
  (off / thematic / score-anchored). → `results/stage3_calendar_ablation.json`.
- `capture_calendars.py` — re-runs one persona through the pipeline and dumps,
  per day, the calendar text fed into Stage 3 plus the LLM's `DailySummary`
  (the corpus does not persist these — they must be regenerated). Parameterised
  by `--persona` and `--backend {routerai, openrouter}`; writes incrementally to
  `results/<persona>_calendars_<backend>.jsonl` so a killed run loses nothing.
- `rerun_authored_calendar.py` — replays a persona's Stage 3 with a frozen
  **hand-authored** calendar, monkeypatching `_format_calendar` so the calendar
  is the *only* changed variable. This is what showed that a well-formed calendar
  still moves no zones. → `results/<persona>_authored_rerun.json`.

**Stage-2 / Stage-3 LLM experiments.**
- `dspy_stage3.py`, `dspy_stage3_eval.py` — **E1**: MIPROv2 prompt optimisation of
  the Stage-3 scorer (returned a no-op).
- `recalibrate_stage2.py` — **E8a**: re-derives danger labels from stored Stage-2
  confidences with grid-searched cutoffs, then replays Stage 4.
- `rerun_stage2.py` — **E8b**: re-runs Stage 2 with the graded-confidence prompt
  variant (`src/prompts_stage2_v2.py`).
- `mindguard_eval.py` — the external-validation run over the MindGuard
  clinician-labelled set, swept across three classifier models.

**`consolidate_results.py`** — collects the per-experiment outputs into
`results/chapter4_consolidated.json`, the single file the chapter's summary
tables draw from.

(The `erisk_*.py` scripts are earlier exploratory work on the eRisk dataset and
are not a chapter result.)

## Production-code changes the experiments required

Three changes were made to `src/behavioral/` so the experiments could run without
forking production behaviour. All three are committed.

- **`risk_engine.py` — Stage-4 made tunable.** Added `DEFAULT_YELLOW_TH` (the
  YELLOW behavioural thresholds, defaults reproducing the original hard-coded
  values exactly) and gave `evaluate_risk_zone` an optional `thresholds` override
  and a `yellow_gate` count. This lets `optimize_thresholds.py` recalibrate by
  replay; with no override, production behaviour is byte-identical.
- **`danger_agg.py` — the aggregation bug fix.** `_aggregate_predictions` used the
  Stage-2 `confidence` field as danger severity without gating it by `label`.
  Now `danger = confidence if label == 1 else 0.0`. This was the cause of the
  false "gpt-oss-120b over-escalates" result (E10); the fix is a no-op on
  deepseek and corrects gpt-oss-120b.
- **`behavioral_llm.py` — calendar anchoring.** `_format_calendar` now appends a
  numeric digest (prior-day zone + peak behavioural score) when a summary carries
  one, and the calendar prompt block instructs Stage 3 to anchor today's scores
  to the prior trend. This is the score-anchored calendar arm E9 evaluates.

## Synthetic corpus generation — `experiments/synthetic/`

The corpus the harness replays is synthetic. The generator turns a persona's
day-script into dialogue turn-by-turn with two model families — a Patient LM
playing the persona and a Clinician LM as the monitored assistant (different
families, to avoid scoring a model against its own prior). `postgen_edit.py` is a
post-generation editor stage that strips generator scaffolding (numbered rule
lists, "do not use markdown" spam, stage directions) into a parallel
`.edited.jsonl` without mutating the raw file. `runner.py` drives the iterative
clean → generate → classify → aggregate loop. The sixteen persona day-scripts are
in `synthetic/personas/`.

## Data artifacts

- **Hand-authored calendars** — `experiments/viktor_calendar_authored.json`,
  `nastya_calendar_authored.json`. Frozen, manually written corrected calendars
  (score trajectory, ordinal tone, day-over-day deltas, trend header) fed by
  `rerun_authored_calendar.py`.
- **Corpus eval files** — `results/corpus/*_corpus_eval.jsonl`: one row per
  persona-day from an `evaluate_corpus.py` run, with its paired `*_summary.json`.
- **Per-experiment result JSON** — `results/`: `threshold_optimization.json`,
  `hysteresis_experiment.json`, `stage4_noise_spikes.json`,
  `stage3_calendar_ablation.json`, `stage2_recalibration.json`,
  `stage2_v2_rerun.json`, `dspy_stage3_*.json`, `gptoss120b_rescored_postfix.json`,
  `chapter4_consolidated.json`.
- **MindGuard outputs** — `results/mindguard/`.
- **Generated dialogue corpus** — `results/pilot/<persona>/`: the raw and
  `.edited.jsonl` synthetic sessions. Large; left untracked in git.
- **Run logs** — `results/*.log`: stdout of long runs; left untracked.

## Provider integrations

Every experiment script reaches its LLM through **`litellm`**, which gives one
OpenAI-compatible interface over all backends. A backend is selected by a
prefixed model string plus, where needed, an `api_base` and an environment key:

- **OpenRouter** — `openrouter/<vendor>/<model>` (e.g.
  `openrouter/openai/gpt-oss-120b`). No `api_base`; key `OPENROUTER_API_KEY`.
- **RouterAI** — `openai/<vendor>/<model>` (e.g. `openai/deepseek/deepseek-v3.2`)
  with `api_base = https://routerai.ru/api/v1`; key `ROUTERAI_API_KEY`.
- **Local Ollama** — `ollama_chat/<model>` with `api_base` pointing at an Ollama
  host (`localhost:11434` or a LAN GPU box); no key.

Keys live only in `ai-safety-dev/.env` (gitignored) and are read via
`os.environ` — passed to `litellm` as parameters, never as command-line
arguments. Each harness run records the model, `api_base` and backend in its
`summary.json`. A standing caveat: pipeline verdicts depend on the backend and
the generator, and the chapter-4 working corpus moved mid-programme from local
gpt-oss-20b to deepseek-v3.2 / gpt-oss-120b — so every result states which corpus
and backend it is on.

## Quick index

| Experiment | Script | Result file |
|---|---|---|
| Replay harness (§4.3–4.5) | `evaluate_corpus.py` | `results/corpus/*_corpus_eval.jsonl` |
| E1 — DSPy Stage-3 prompt opt | `dspy_stage3.py`, `dspy_stage3_eval.py` | `results/dspy_stage3_*.json` |
| E8a — Stage-2 recalibration | `recalibrate_stage2.py` | `results/stage2_recalibration.json` |
| E8b — Stage-2 graded prompt | `rerun_stage2.py` | `results/stage2_v2_rerun.json` |
| E9 — calendar ablation | `stage3_calendar_ablation.py` | `results/stage3_calendar_ablation.json` |
| E9 follow-up — calendar capture / rerun | `capture_calendars.py`, `rerun_authored_calendar.py` | `results/*_calendars_*.json`, `*_authored_rerun.json` |
| E11 — Stage-4 noise spikes | `stage4_noise_spikes.py` | `results/stage4_noise_spikes.json` |
| MindGuard external validation | `mindguard_eval.py` | `results/mindguard/` |
| Threshold optimisation | `optimize_thresholds.py` | `results/threshold_optimization.json` |
| Hysteresis search | `hysteresis_experiment.py` | `results/hysteresis_experiment.json` |
| Consolidation | `consolidate_results.py` | `results/chapter4_consolidated.json` |
