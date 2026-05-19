# Chapter 4 Experiments — Handoff for Sonya

**2026-05-18, English.** This document explains everything done in the
chapter-4 experiment session: what was run, what was found, the two harnesses
built (how to use and extend them), and what is left for you to do.

Read alongside:
- `ai-safety-dev/experiments/chapter4-experiment-plan.md` — the experiment design
  (E0–E8, the calibration-vs-evaluation logic, the DSPy plan);
- `ai-safety-dev/experiments/results/chapter4-results.md` — the raw numbers;
- `Sophiya/2026-05-13-draft4/chapter4-draft.md` — the chapter draft to revise.

---

## What was done

**Repository.** `origin/main` was merged into the workshop branch (clean, commit
`42eb40f`). Two bugs were found and fixed — **these fixes are not committed yet**,
commit them when you are ready:
- `src/main.py` — `weekly_scheduler(wait=False)` → `weekly_scheduler.shutdown(wait=False)`
  (the lifespan shutdown called the scheduler object instead of its method);
- `src/behavioral/weekly_report.py` — `scores.get("delusion", 0)` →
  `scores.get("delusional", 0)` (the key is `delusional` everywhere else, so the
  weekly report was always reading 0).

**Two harnesses built** (see next section).

**Experiments run** (all 2026-05-18, temperature 0 throughout):
- **E0/E8 — external classifier validation.** The 5-class classifier run over
  the MindGuard clinician-labelled dataset (1134 turns), with three classifier
  models, to validate it against non-author ground truth.
- **E2/E3/E4 — corpus zone baseline.** All 16 personas replayed through the full
  4-stage pipeline; the persona × day → zone table produced.
- **E6 — generator sensitivity.** 11 personas run on both the DeepSeek and
  qwen3.6 corpora to test whether verdicts depend on the generator.
- **Stage-4 recalibration — threshold optimisation + hysteresis** (done,
  offline). Re-fitting the YELLOW thresholds and adding hysteresis to the
  deterministic rule engine — see "Stage-4 recalibration" below.
- **E5 — repeatability** — stopped (low priority at temperature 0).
- **E1/E7 — DSPy prompt optimisation** — not started; see "What is left".

**Main finding.** The pipeline recovers GREEN and RED reasonably (F1 ≈ 0.73–0.77)
but **does not hold the YELLOW zone** (F1 0.19): of 72 YELLOW-designed day-points
only 8 are predicted YELLOW. Escalation personas reach RED several days too
early; the recovery and sustained-YELLOW personas are not reproduced. This is
exactly the "better YELLOW/RED" problem you raised — now quantified, and traced
to its cause by the Stage-4 audit below.

**The YELLOW investigation (2026-05-18).** A targeted audit of all 72
YELLOW-designed day-points found the band is squeezed from **two opposite
sides** — and an early hypothesis was wrong, which is worth recording:

- *First hypothesis (wrong).* We suspected the asymmetric Stage-4 rule "any one
  suicide flag → immediate RED" combined with a ≈4 % classifier false-positive
  rate. Checked against the run data, that rule was **never the sole RED driver**
  on any of the 24 YELLOW→RED days.
- *24 YELLOW→RED — the upper edge.* The real RED drivers are high-confidence
  single-message triggers: `psychosis_max > 0.8` (17 of 24 days) and
  `suicide_max > 0.7` (16 of 24). On mild-distress days the Stage-2 classifier
  returns *maximum-confidence* psychosis/suicide labels. The Stage-4 rule is
  fine; the **classifier is over-confident**. → a prompt-level fault → DSPy.
- *40 YELLOW→GREEN — the lower edge.* All 40 produced **zero** Stage-4 triggers.
  But Stage 3 did detect distress (`topic_concentration` mean 0.34 / max 0.90,
  `emotional_attachment` up to 0.70, isolation 0.1–0.45). Every score lands
  *below* its YELLOW threshold (0.7 / 0.5 / 0.6 / 0.4). The **Stage-4 YELLOW
  thresholds sit above the moderate-distress band**. → a threshold recalibration,
  not a DSPy task.

So YELLOW is degenerate: to trip 2 YELLOW triggers a day must score near-severe,
where the over-confident classifier already trips RED.

**Stage-4 recalibration (done, offline).** Because Stage 4 is a deterministic
rule engine, the audit could be acted on with no model calls — replay the engine
over the stored Stage-1/2/3 outputs with new parameters. Two harnesses,
12-persona calibration set + held-out 4-persona evaluation set:

- `optimize_thresholds.py` — re-fit the five YELLOW behavioural thresholds; all
  five collapsed 0.4–0.7 → a uniform **0.25** (the level where calm and
  moderate-distress days actually separate).
- `hysteresis_experiment.py` — added upward hysteresis: report a higher zone
  only after k consecutive confirming days; search picked **k_red=2, k_yellow=1**.

Combined effect, all 16 personas: zone-match 0.66 → 0.73, macro-F1 0.56 → 0.70,
**YELLOW F1 0.19 → 0.55**, GREEN false-positive rate 0.06 → **0.00**,
escalation-timing error 3.7 d → **1.0 d**. Holdout (4 unseen personas): macro-F1
0.76 — no overfit. Cost: RED recall 0.81 → 0.67 (the confirmation lag). The
residual YELLOW gap (33/72 still → GREEN) is now a **Stage-3** problem — the
behavioural LLM under-scores moderate distress. Numbers: `chapter4-results.md`.

---

## The harnesses

Both live in `ai-safety-dev/experiments/`, are self-contained, and write a
`summary.json` recording every varied and fixed variable (the chapter-4
reproducibility record).

### `mindguard_eval.py` — external classifier validation

Runs the 5-class classifier over the MindGuard testset and scores it against the
clinician labels (binary safe/unsafe gate, self-harm class, per-class
false-positive map).

```
# full run, one classifier model
python mindguard_eval.py --model ollama_chat/gpt-oss-safeguard:latest \
                         --api-base http://192.168.87.25:11434
# smoke test on 30 stratified rows
python mindguard_eval.py --limit 30
```

Key flags: `--model`, `--api-base`, `--api-key`, `--temperature` (default 0),
`--concurrency`, `--limit`. Output: `results/mindguard/mindguard_<model>_<ts>.jsonl`
(per-row) and `.summary.json` (metrics + reproducibility block).

### `evaluate_corpus.py` — corpus zone-reproduction

Replays the synthetic persona corpus through the 4-stage pipeline and produces
the persona × day → zone table plus the six chapter-4 metrics. It **reuses the
production stage logic verbatim** — Stage-1 formulas, Stage-2 `_aggregate_predictions`,
the Stage-3 prompt builder/parser, Stage-4 `evaluate_risk_zone` — and only swaps
the data-access layer (corpus JSONL instead of the live database).

```
# full 16-persona run on the local box
python evaluate_corpus.py --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://192.168.87.25:11434 \
  --stage3-model    ollama_chat/gpt-oss:latest           --stage3-api-base    http://192.168.87.25:11434
# smoke test
python evaluate_corpus.py --personas viktor --limit-days 4
```

Key flags: `--personas` (default all 16), `--generator` (`qwen36` | `deepseek`),
`--classifier-model` / `--classifier-api-base`, `--stage3-model` /
`--stage3-api-base`, `--temperature` (default 0), `--concurrency` (personas in
parallel), `--limit-days` (smoke). Output: `results/corpus/<ts>_corpus_eval.jsonl`
(one line per persona-day, with all four stages' metrics) and `<ts>_summary.json`.

For cloud providers (OpenRouter, RouterAI) pass the `openrouter/...` or
`openai/...` model string and an **empty** `--*-api-base` so litellm routes
correctly; the key is read from `.env`.

### `consolidate_results.py`

Merges corpus JSONL files into per-run and per-persona metrics and writes
`results/chapter4_consolidated.json`. Edit the `RUNS` dict to point at the files
you want merged (the baseline is the qwen36 E6 leg + the qwen36 top-up).

### `optimize_thresholds.py` — Stage-4 threshold recalibration

Offline (no GPU, no model calls): replays the deterministic Stage-4 engine over
the stored baseline JSONL with candidate YELLOW thresholds. Splits the personas
into a calibration set and a random 4-persona holdout, initialises each
threshold by Youden's J, refines by coordinate descent under an FPR-on-GREEN
constraint. Output: `results/threshold_optimization.json`. No flags — edit
`BASELINE_FILES` / `SEED` / `GRID` at the top of the file. Depends on the
`thresholds` / `yellow_gate` arguments added to `risk_engine.evaluate_risk_zone`
(defaults reproduce the original behaviour exactly).

### `hysteresis_experiment.py` — Stage-4 hysteresis

Offline, runs on top of the optimised thresholds (reads
`threshold_optimization.json`). Adds upward hysteresis — a higher zone is
reported only after k consecutive confirming days — and grid-searches `k_red`,
`k_yellow`. Output: `results/hysteresis_experiment.json`, including the
consolidated pre-DSPy confusion matrix and the escalation-timing table. Imports
the shared helpers from `optimize_thresholds.py`.

---

## How to extend the harnesses

- **A new classifier or Stage-3 model** — no code change, just `--model` /
  `--classifier-model` / `--stage3-model` and the matching `--api-base`. Each run
  self-documents in `summary.json`, so model-sweep experiments need only a loop.
- **A new metric** — add it to `compute_metrics()` in `evaluate_corpus.py` (or
  `_summarise()` in `mindguard_eval.py`). The per-row JSONL already stores every
  stage's raw output, so most metrics can also be computed offline from the JSONL
  without re-running.
- **A new persona** — add a day-script under `synthetic/personas/`, register it
  in `personas/__init__.py::ALL_PERSONAS`, generate its corpus; the harness picks
  it up automatically.
- **Repeated runs (E5)** — invoke the harness N times; each writes a timestamped
  output. `consolidate_results.py` can then compare them.
- **The pipeline changed** — because the harness imports the production stage
  functions, a change in `src/behavioral/` is reflected automatically; only the
  data-access shim in the harness is custom.

A caveat to know: the harness imports `behavioral.*`, which transitively
constructs `config.Settings()`. The harness sets dummy DB/Langfuse env vars so
this import succeeds without a database — it never touches the DB. If you add a
stage that *does* read the DB, that shim will need revisiting.

---

## What the results say (short version)

| Experiment | Headline |
|---|---|
| E0/E8 MindGuard | gpt-oss-safeguard is the cleanest classifier (FPR 3.75 %); the depression-class over-fire is a nemotron artifact; the suicide class over-fires ≈4 % on every model |
| E2/E3/E4 corpus | zone-match 0.66, macro-F1 0.56; **YELLOW F1 only 0.19**; escalation fires too early; no exact trajectory match |
| E6 generator | verdicts shift with the generator (zone-match 0.62 vs 0.57) — a construct-validity caveat |
| Stage-4 recalibration | threshold re-fit + hysteresis: macro-F1 0.56 → 0.70, **YELLOW F1 0.19 → 0.55**, GREEN FP rate → 0.00, escalation timing 3.7 d → 1.0 d (held-out confirmed) |

Full numbers and tables: `chapter4-results.md`.

---

## What is left for you to do

1. **Commit the two bug fixes** (`main.py`, `weekly_report.py`) when ready.
2. **Regenerate two personas** — the qwen3.6 corpus is incomplete for `dmitry`
   (13 of 17 days) and `rina` (6 of 10 days). Regenerate, then re-run the
   baseline so §4.3 is on a complete corpus.
3. **DSPy on Stage 3 (E1).** The Stage-4 recalibration is done; the residual
   YELLOW gap is Stage-3 *under-scoring* moderate distress (33 of 72 YELLOW
   day-points still collapse to GREEN) and a few *over-scores* (5 → RED). Both
   are the same root cause — Stage 3 emits near-binary, uncalibrated scores. The
   DSPy pass targets the Stage-3 behavioural prompt: optimise it to emit a
   calibrated graded 0–1 intensity. Scaffold: `experiments/dspy_stage3.py`;
   `dspy` 3.1.3 installed. Needs model calls → run on cloud / `192.168.87.25`,
   not the local GPU. The Stage-2 classifier pass is now a minor cleanup (only
   4 residual day-points) and optional.
4. **Prompt A/B (E7).** After E1, re-run `evaluate_corpus.py` with the optimised
   Stage-3 prompt *and* the recalibrated engine, compare to the consolidated
   pre-DSPy baseline in `chapter4-results.md` — that is the YELLOW-repair result
   that belongs in the chapter.
5. **Revise the chapter draft.** `chapter4-draft.md` follows your scaffold and
   has the real numbers; revise the prose, translate to Russian, and decide which
   negative results to foreground (the scaffold is clear that they are the
   contribution, not a problem).
6. **Calibration vs evaluation.** The synthetic-corpus results are
   calibration-convergence — the thresholds were set with these personas in
   view. If you can hold out 1–2 personas from threshold tuning and re-run, §4.3
   becomes a real evaluation. This is worth doing before the defence.

---

## Infrastructure notes

- **Backends used:** local Ollama, remote Ollama at `192.168.87.25:11434` (the
  3090 box), RouterAI, OpenRouter. RouterAI and OpenRouter both rate-limit the
  small `gpt-oss-safeguard-20b` model — for that model prefer an Ollama host.
- **Pick one backend and keep it fixed** for any experiments meant to be
  compared — the runs showed pipeline output depends on the backend.
- API keys (`ROUTERAI_API_KEY`, `OPENROUTER_API_KEY`) live in
  `ai-safety-dev/.env`, which is gitignored — keep it that way.
