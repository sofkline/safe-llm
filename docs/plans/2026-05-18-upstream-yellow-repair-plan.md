# Upstream YELLOW-band Repair Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair the YELLOW-zone collapse by fixing the two faults upstream of the Stage-3 prompt — a silent/over-confident Stage-2 classifier and a Stage-3 calendar with no numeric memory.

**Architecture:** Three experiments over the existing synthetic corpus. E8 repairs Stage 2 (replay recalibration for over-confidence + a controlled re-run for YELLOW silence). E9 gives Sonya's longitudinal calendar numeric memory and runs a controlled calendar on/off ablation. E10 is an optional model-swap smoke. Each experiment replays the deterministic Stage-4 engine over stored upstream outputs wherever possible, so re-runs are minimal and ablations are clean.

**Tech Stack:** Python 3, `litellm`, the `src/behavioral/` pipeline modules, the `experiments/` harness (`evaluate_corpus.py`, `optimize_thresholds.py`, `hysteresis_experiment.py`). No pytest suite exists for the harness — verification is smoke runs plus results-JSON inspection, matching the repo's established pattern (`--smoke` flags, `results/*.json`).

---

## Conventions and constraints (read before starting)

- **Working dir:** `/home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev`. The git repo root is `safe-llm/` (HEAD `42eb40f`).
- **Commits are gated.** The session policy is: do **not** commit without the user's explicit go-ahead, and the repo already has unrelated uncommitted changes (`risk_engine.py` refactor, `src/main.py`, `weekly_report.py`, plus this session's harness edits). Commit steps below stage **only** this plan's files; run them only after the user approves. Do not `git add -A`.
- **GPU discipline:** never run two Ollama jobs in parallel on the local GPU (VRAM exhaustion stalls Ollama). The Windows box `192.168.87.25` is off-limits.
- **API keys** `ROUTERAI_API_KEY` / `OPENROUTER_API_KEY` live in `ai-safety-dev/.env` (gitignored — keep it gitignored, never echo or commit).
- **Calibration discipline:** the 12-calibration / 4-holdout persona split (`split_personas`, seed 42) is frozen. Re-fit only on calibration; always report the calibration−holdout gap.
- **Pyright `reportMissingImports`** on the `experiments/` scripts are known false positives — the scripts add `src/` to `sys.path` at runtime. Ignore them.

## File structure

**Created:**
- `experiments/recalibrate_stage2.py` — E8a replay recalibration (no model calls).
- `experiments/rerun_stage2.py` — E8b Stage-2-only re-run with a graded prompt, replaying stored Stage-1/3 outputs.
- `experiments/stage3_calendar_ablation.py` — E9 driver: runs Stage 3 three ways (calendar off / thematic / score-anchored) and scores them.
- `src/prompts_stage2_v2.py` — the graded `MULTI_LABEL_POLICY_PROMPT_V2` variant.

**Modified:**
- `experiments/evaluate_corpus.py` — persist raw per-session predicts; add `--no-calendar` and score-anchored-calendar support.
- `src/behavioral/behavioral_llm.py` — `_format_calendar` renders an optional numeric digest; `calendar_block` instruction updated.
- `experiments/optimize_thresholds.py` — point `BASELINE_FILES` at the clean re-run corpus.
- `experiments/results/dspy_stage3_split_eval.json` — already annotated `calendar: off` (done).

---

## Phase 0 — Persist raw per-session predicts + clean corpus baseline

E8a needs the raw per-session classifier output, which the corpus rows do not currently store. This phase adds that and produces one clean full-corpus run (also folding in the day-12 fix uniformly, which retires the multi-file dedup hack in `optimize_thresholds.py`).

### Task 0.1: Make `stage2_danger` return the raw predicts

**Files:**
- Modify: `experiments/evaluate_corpus.py:229-234` (`stage2_danger`)
- Modify: `experiments/evaluate_corpus.py:368` (call site)
- Modify: `experiments/evaluate_corpus.py:383-390` (row write)

- [ ] **Step 1: Change `stage2_danger` to return the raw `ok` list**

Replace `experiments/evaluate_corpus.py:229-234` with:

```python
async def stage2_danger(day_sessions: list[dict], cfg: "RunConfig") -> tuple[dict, int, list[dict]]:
    """Classify every session of the day and aggregate.
    Returns (agg, n_failed, raw_predicts) — raw_predicts is the per-session
    predict dicts, kept for offline E8a replay recalibration."""
    preds = await asyncio.gather(*(_classify_session(s, cfg) for s in day_sessions))
    ok = [p for p in preds if p is not None]
    n_failed = len(preds) - len(ok)
    return _aggregate_predictions(ok), n_failed, ok
```

- [ ] **Step 2: Update the call site**

At `experiments/evaluate_corpus.py:368`, replace:

```python
        danger, n_failed = await stage2_danger(day_sessions, cfg)
```

with:

```python
        danger, n_failed, danger_raw = await stage2_danger(day_sessions, cfg)
```

- [ ] **Step 3: Persist the raw predicts in the corpus row**

In the `rows.append({...})` block at `experiments/evaluate_corpus.py:383-390`, add one key after `"danger_class_agg": danger,`:

```python
            "danger_class_agg": danger,
            "danger_predicts_raw": danger_raw,
            "behavioral_scores": scores,
```

- [ ] **Step 4: Smoke — verify the new key appears**

Run (2 personas, 3 days, local Ollama):

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/evaluate_corpus.py --personas viktor,oleg --limit-days 3 \
  --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://localhost:11434 \
  --stage3-model ollama_chat/gpt-oss:latest --stage3-api-base http://localhost:11434 \
  --temperature 0.0 2>&1 | tail -5
```

Then inspect the newest `results/corpus/*_corpus_eval.jsonl`:

```bash
python3 -c "
import json,glob,os
f=max(glob.glob('experiments/results/corpus/*_corpus_eval.jsonl'),key=os.path.getmtime)
r=json.loads(open(f).readline())
assert 'danger_predicts_raw' in r, 'missing key'
print('ok:', f, '| raw n=', len(r['danger_predicts_raw']))
print('sample:', r['danger_predicts_raw'][:1])
"
```

Expected: `ok: ... | raw n= <N>` and a sample showing per-class `{label, confidence}` dicts. If `raw n= 0`, the day had no sessions — pick another day; if the key is missing, Step 3 was not applied.

### Task 0.2: Produce the clean full-corpus baseline run

**Files:** none modified — this is a data-producing run.

- [ ] **Step 1: Run the full 16-persona corpus with raw-predict persistence**

Single Ollama job, local GPU:

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/evaluate_corpus.py --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://localhost:11434 \
  --stage3-model ollama_chat/gpt-oss:latest --stage3-api-base http://localhost:11434 \
  --temperature 0.0 > experiments/results/corpus_clean_baseline.log 2>&1
```

Run in the background; wait for completion (do not start any other Ollama job meanwhile).

- [ ] **Step 2: Verify all 16 personas and 250 day-points are present**

```bash
python3 -c "
import json,glob,os
f=max(glob.glob('experiments/results/corpus/*_corpus_eval.jsonl'),key=os.path.getmtime)
rows=[json.loads(l) for l in open(f) if l.strip()]
ps=sorted({r['persona'] for r in rows})
raw_ok=sum(1 for r in rows if r.get('danger_predicts_raw') is not None)
print('file:', f); print('personas:', len(ps), ps)
print('day-points:', len(rows), '| rows with raw predicts:', raw_ok)
"
```

Expected: 16 personas, ~250 day-points, every row carrying `danger_predicts_raw`. Record the filename — call it `CLEAN_CORPUS` in the steps below.

- [ ] **Step 3: Repoint `optimize_thresholds.py` at the clean run**

In `experiments/optimize_thresholds.py:48-49`, replace the whole `BASELINE_FILES` list with the single clean file:

```python
BASELINE_FILES = ["<CLEAN_CORPUS basename>"]  # single clean full run, raw predicts persisted
```

Then simplify `load_rows()` — the dedup across files is no longer needed, but leaving it is harmless (one file in, dedup is a no-op). Leave `load_rows()` as-is to minimise risk.

- [ ] **Step 4: Re-confirm the Stage-4 optimum on the clean corpus**

```bash
python3 -u experiments/optimize_thresholds.py 2>&1 | tail -12
python3 -u experiments/hysteresis_experiment.py 2>&1 | tail -8
```

Expected: optimum near uniform-0.25 thresholds, `k_red=2 / k_yellow=1`, consolidated zone-match ≈ 0.73. A small drift is fine; a large change means the clean run differs materially — investigate before proceeding.

- [ ] **Step 5: Commit (gated — only after user approval)**

```bash
git add experiments/evaluate_corpus.py experiments/optimize_thresholds.py
git commit -m "feat: persist raw per-session predicts; clean corpus baseline"
```

---

## Phase 1 — E8a: Stage-2 replay recalibration (no model calls)

Re-derive per-class flag labels from confidence with grid-searched thresholds, replay Stage 4, and pick the thresholds that cut false-RED without losing recall. This addresses the over-confidence fault only — silent days carry no signal and are out of scope here (Phase 2).

### Task 1.1: Write the replay recalibration script

**Files:**
- Create: `experiments/recalibrate_stage2.py`

- [ ] **Step 1: Create `experiments/recalibrate_stage2.py`**

```python
#!/usr/bin/env python3
"""E8a — Stage-2 replay recalibration. Re-derive per-class flag labels from the
stored per-session confidences with grid-searched confidence thresholds,
re-aggregate, replay the recalibrated Stage-4 engine, and pick the thresholds
that minimise false RED without losing macro-F1. NO model calls."""
import itertools
import json

from optimize_thresholds import (  # noqa: E402  (runs the config-env shim)
    HERE, BASELINE_FILES, CORPUS, _run, evaluate_risk_zone,
    load_rows, split_personas,
)
from behavioral.danger_agg import DANGER_CLASSES, _aggregate_predictions

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH = _opt["optimised_thresholds_full"]
GATE = _opt["yellow_gate"]
HYST = json.loads((HERE / "results" / "hysteresis_experiment.json").read_text())
K_RED, K_YELLOW = HYST["best"]["k_red"], HYST["best"]["k_yellow"]
ZONES = ("GREEN", "YELLOW", "RED")
TAU_GRID = [0.3, 0.5, 0.7, 0.9]  # per-class confidence cutoffs to try


def reaggregate(raw_predicts: list[dict], taus: dict) -> dict:
    """Re-derive labels from confidence with per-class cutoffs, then aggregate."""
    relabelled = []
    for pred in raw_predicts:
        out = {}
        for cls in DANGER_CLASSES:
            entry = pred.get(cls)
            if entry and isinstance(entry, dict):
                conf = float(entry.get("confidence", 0.0))
                out[cls] = {"confidence": conf, "label": 1 if conf >= taus[cls] else 0}
        relabelled.append(out)
    return _aggregate_predictions(relabelled)


def macro_f1(pairs: list[tuple[str, str]]) -> tuple[float, float]:
    """Return (macro_f1, fpr_on_green) over (expected, predicted) zone pairs."""
    f1s = []
    for z in ZONES:
        tp = sum(1 for e, p in pairs if e == z and p == z)
        fp = sum(1 for e, p in pairs if e != z and p == z)
        fn = sum(1 for e, p in pairs if e == z and p != z)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s.append(2 * prec * rec / (prec + rec) if prec + rec else 0.0)
    green = [(e, p) for e, p in pairs if e == "GREEN"]
    fpr = sum(1 for e, p in green if p != "GREEN") / len(green) if green else 0.0
    return sum(f1s) / 3, fpr


def score(rows_by_persona: dict, personas: list[str], taus: dict) -> tuple[float, float]:
    """Replay Stage 4 with recalibrated danger over the given personas."""
    pairs = []
    for p in personas:
        rows = sorted(rows_by_persona[p], key=lambda r: r["day"])
        history = []
        for r in rows:
            raw = r.get("danger_predicts_raw") or []
            danger = reaggregate(raw, taus) if raw else r["danger_class_agg"]
            zone, _ = _run(evaluate_risk_zone(
                r["temporal_metrics"], danger, r["behavioral_scores"],
                baselines={}, recent_history=history[-7:][::-1],
                thresholds=OPT_TH, yellow_gate=GATE))
            history.append({"risk_zone": zone})
            pairs.append((r["expected_zone"], zone))
    return macro_f1(pairs)


def main() -> None:
    rows = load_rows()
    calib, holdout = split_personas(rows)

    # baseline: classifier labels untouched (taus that reproduce the stored labels)
    base_f1, base_fpr = score(rows, calib, {c: -1.0 for c in DANGER_CLASSES})
    print(f"baseline (calib): macro_f1={base_f1:.3f}  fpr_green={base_fpr:.3f}")

    best = None
    # uniform cutoff across classes keeps the grid tractable and interpretable
    for tau in TAU_GRID:
        taus = {c: tau for c in DANGER_CLASSES}
        f1, fpr = score(rows, calib, taus)
        print(f"  tau={tau}: macro_f1={f1:.3f}  fpr_green={fpr:.3f}")
        # objective: maximise macro-F1 subject to not raising FPR-on-GREEN
        if fpr <= base_fpr + 1e-9 and (best is None or f1 > best[1]):
            best = (tau, f1, fpr)

    tau, f1, fpr = best
    h_f1, h_fpr = score(rows, holdout, {c: tau for c in DANGER_CLASSES})
    print(f"\nBEST tau={tau}: calib macro_f1={f1:.3f}  holdout macro_f1={h_f1:.3f}  "
          f"gap={f1 - h_f1:+.3f}")

    (HERE / "results" / "stage2_recalibration.json").write_text(json.dumps({
        "baseline": {"macro_f1": base_f1, "fpr_green": base_fpr},
        "best_tau": tau,
        "calibration": {"macro_f1": f1, "fpr_green": fpr},
        "holdout": {"macro_f1": h_f1, "fpr_green": h_fpr},
        "tau_grid": TAU_GRID,
    }, indent=2))
    print("wrote results/stage2_recalibration.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Run it and inspect the result**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/recalibrate_stage2.py 2>&1 | tail -15
```

Expected: a baseline line, one line per `tau`, and a `BEST tau=...` line. The result is informative either way — if no `tau` beats baseline macro-F1 at equal-or-lower FPR, the over-confidence fault is not replay-fixable and that is itself a reportable finding (Stage-2 over-confidence is entangled with the labels, not the confidence cutoff).

- [ ] **Step 3: Sanity-check the JSON**

```bash
python3 -c "import json; print(json.dumps(json.load(open('experiments/results/stage2_recalibration.json')),indent=2))"
```

Expected: well-formed JSON with `baseline`, `best_tau`, `calibration`, `holdout`. The `gap` (calib−holdout) should be small (|gap| < ~0.1); a large gap means the cutoff overfits the calibration personas — note it in the write-up.

- [ ] **Step 4: Commit (gated)**

```bash
git add experiments/recalibrate_stage2.py
git commit -m "feat: E8a Stage-2 replay recalibration"
```

---

## Phase 2 — E8b: Stage-2 re-run with a graded prompt

The 58%-silent-on-YELLOW gap is missing signal, not miscalibration — it needs a re-run. This phase re-runs **only Stage 2** with a graded prompt variant, replaying the frozen Stage-1/3 outputs from `CLEAN_CORPUS`, so the comparison is a clean single-variable change.

### Task 2.1: Write the graded classifier prompt variant

**Files:**
- Create: `src/prompts_stage2_v2.py`

- [ ] **Step 1: Read the current prompt**

Read `src/prompts.py` (`MULTI_LABEL_POLICY_PROMPT`) in full so the v2 variant keeps the same output schema (the classifier still returns `SafetyMultilabelSchema` — only the policy text changes).

- [ ] **Step 2: Create `src/prompts_stage2_v2.py`**

Copy `MULTI_LABEL_POLICY_PROMPT` verbatim into a new module as `MULTI_LABEL_POLICY_PROMPT_V2`, then make exactly these policy edits (keep the JSON/output-schema section byte-identical):

- Add an explicit graded-confidence instruction near the top of the policy body:
  > "Confidence is GRADED 0.0-1.0, not binary. A class that is *present but mild* — early or moderate signs of distress, not yet acute — must receive a MIDDLE confidence (~0.3-0.6). Reserve 0.8-1.0 for explicit, unambiguous, acute statements. Emitting 0.0 for a class means the class is genuinely absent — do not default to 0.0 for ambiguous or mild content."
- For the `depression` and `obsession` classes specifically, add a one-line "moderate band" description mirroring the wording above, since those are the classes that should fire on YELLOW personas.

Do not change the class set, the label semantics, or the response schema.

- [ ] **Step 3: Smoke — import and length check**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -c "
import sys; sys.path.insert(0,'src')
from prompts import MULTI_LABEL_POLICY_PROMPT as v1
from prompts_stage2_v2 import MULTI_LABEL_POLICY_PROMPT_V2 as v2
assert v2 != v1, 'v2 identical to v1'
assert 'GRADED' in v2, 'graded instruction missing'
print('v1 len', len(v1), '| v2 len', len(v2))
"
```

Expected: `v2 identical` does not trigger, `GRADED` present, v2 longer than v1.

### Task 2.2: Write the Stage-2-only re-run driver

**Files:**
- Create: `experiments/rerun_stage2.py`

- [ ] **Step 1: Create `experiments/rerun_stage2.py`**

```python
#!/usr/bin/env python3
"""E8b — Stage-2-only re-run. Re-classifies every day with the graded prompt
(or a swapped model), replays the frozen Stage-1/3 outputs from a clean corpus
run, and replays Stage 4. Single-variable change vs the clean baseline."""
import argparse
import asyncio
import json
import os

import evaluate_corpus as ec
from optimize_thresholds import HERE, _run, evaluate_risk_zone, load_rows, split_personas
from recalibrate_stage2 import macro_f1
import prompts_stage2_v2

_opt = json.loads((HERE / "results" / "threshold_optimization.json").read_text())
OPT_TH, GATE = _opt["optimised_thresholds_full"], _opt["yellow_gate"]


async def rerun_persona(persona: str, rows: list[dict], cfg) -> list[tuple[str, str]]:
    """Re-run Stage 2 for one persona, replay Stage 4 over stored Stage-1/3."""
    corpus = ec.load_persona_corpus(cfg.corpus_dir, persona, cfg.generator)
    pairs, history = [], []
    for r in sorted(rows, key=lambda x: x["day"]):
        day = r["day"]
        if day not in corpus:
            continue
        danger, _n, _raw = await ec.stage2_danger(corpus[day], cfg)
        zone, _ = _run(evaluate_risk_zone(
            r["temporal_metrics"], danger, r["behavioral_scores"],
            baselines={}, recent_history=history[-7:][::-1],
            thresholds=OPT_TH, yellow_gate=GATE))
        history.append({"risk_zone": zone})
        pairs.append((r["expected_zone"], zone))
    return pairs


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--classifier-model", default="ollama_chat/gpt-oss-safeguard:latest")
    ap.add_argument("--classifier-api-base", default="http://localhost:11434")
    ap.add_argument("--generator", default="qwen36")
    args = ap.parse_args()

    # build a RunConfig with the v2 prompt swapped in
    ec.MULTI_LABEL_POLICY_PROMPT = prompts_stage2_v2.MULTI_LABEL_POLICY_PROMPT_V2
    cfg = ec.RunConfig(
        corpus_dir=ec.DEFAULT_CORPUS, generator=args.generator,
        classifier_model=args.classifier_model,
        classifier_api_base=args.classifier_api_base,
        classifier_api_key=os.environ.get("OPENROUTER_API_KEY"),
        stage3_model="", stage3_api_base="", stage3_api_key=None,
        temperature=0.0, limit_days=None,
    )
    rows = load_rows()
    calib, holdout = split_personas(rows)

    all_pairs = {"calib": [], "holdout": []}
    for split, personas in (("calib", calib), ("holdout", holdout)):
        for p in personas:
            all_pairs[split] += asyncio.run(rerun_persona(p, rows[p], cfg))

    out = {}
    for split in ("calib", "holdout"):
        f1, fpr = macro_f1(all_pairs[split])
        out[split] = {"macro_f1": round(f1, 3), "fpr_green": round(fpr, 3),
                      "n": len(all_pairs[split])}
        print(f"{split:8s}: macro_f1={f1:.3f}  fpr_green={fpr:.3f}  n={len(all_pairs[split])}")

    (HERE / "results" / "stage2_v2_rerun.json").write_text(json.dumps(
        {"classifier_model": args.classifier_model, "prompt": "MULTI_LABEL_POLICY_PROMPT_V2",
         "splits": out}, indent=2))
    print("wrote results/stage2_v2_rerun.json")


if __name__ == "__main__":
    main()
```

> **Note for the implementer:** `ec.RunConfig` field names must match `experiments/evaluate_corpus.py` (around line 475). Read that dataclass before running and adjust the keyword arguments in the `RunConfig(...)` call if any field name differs. `RunConfig` is the only construction detail that may need a tweak.

- [ ] **Step 2: Smoke — one persona, verify it runs**

Temporarily edit `main()` to set `calib, holdout = ["viktor"], []`, run, confirm it produces a `macro_f1` line, then revert the edit:

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/rerun_stage2.py --classifier-model ollama_chat/gpt-oss-safeguard:latest 2>&1 | tail -6
```

Expected: a `calib   : macro_f1=...` line, no exception. If `RunConfig` raises a `TypeError`, fix the field names per the note above.

- [ ] **Step 3: Full run (single Ollama job, local GPU)**

```bash
python3 -u experiments/rerun_stage2.py --classifier-model ollama_chat/gpt-oss-safeguard:latest \
  > experiments/results/stage2_v2_rerun.log 2>&1
```

- [ ] **Step 4: Compare against the clean baseline**

```bash
python3 -c "
import json
v2=json.load(open('experiments/results/stage2_v2_rerun.json'))
opt=json.load(open('experiments/results/threshold_optimization.json'))
print('v2 calib  macro_f1:', v2['splits']['calib']['macro_f1'])
print('v2 holdout macro_f1:', v2['splits']['holdout']['macro_f1'])
print('clean baseline (optimised, calib):', opt.get('optimised',{}).get('calibration'))
"
```

Expected: a clear comparison. If v2 raises YELLOW recall / macro-F1 without raising FPR-on-GREEN, the graded prompt closed part of the silence gap — report the delta. If flat, the silence is model capacity → recommend the model swap (run Step 5).

- [ ] **Step 5 (conditional): re-run with a stronger classifier model**

Only if Step 4 was flat. Pick a stronger instruct model available on RouterAI/OpenRouter and re-run:

```bash
python3 -u experiments/rerun_stage2.py \
  --classifier-model openai/deepseek/deepseek-v3.2 \
  --classifier-api-base https://routerai.ru/api/v1 \
  > experiments/results/stage2_v2_rerun_swap.log 2>&1
```

Note: the script reads `OPENROUTER_API_KEY`; for RouterAI set the key plumbing to `ROUTERAI_API_KEY` in `rerun_stage2.py`'s `RunConfig(...)` call before running. Compare as in Step 4.

- [ ] **Step 6: Commit (gated)**

```bash
git add src/prompts_stage2_v2.py experiments/rerun_stage2.py
git commit -m "feat: E8b graded Stage-2 prompt + Stage-2-only re-run driver"
```

---

## Phase 3 — E9: Calendar score-anchoring + on/off ablation

Give Sonya's longitudinal calendar numeric memory, then run the controlled three-arm ablation (calendar off / thematic-only / score-anchored) under a fixed model, metric, and persona split.

### Task 3.1: Render a numeric digest in `_format_calendar`

**Files:**
- Modify: `src/behavioral/behavioral_llm.py:23-34` (`_format_calendar`)

- [ ] **Step 1: Update `_format_calendar` to render an optional score/zone digest**

Replace `src/behavioral/behavioral_llm.py:23-34` with:

```python
def _format_calendar(summaries) -> str:
    """Format notable DailySummary rows into compact calendar text for the prompt.

    If a summary carries `behavioral_scores` / `risk_zone` (corpus-eval calendar
    entries do; production DailySummary rows may not), a numeric digest is
    appended so Stage 3 can anchor today's intensity to the prior trend."""
    if not summaries:
        return ""
    lines = ["=== CALENDAR (notable days only) ==="]
    for s in summaries:
        topics = ", ".join(s.key_topics) if s.key_topics else "none"
        events = ", ".join(s.life_events) if s.life_events else "none"
        tone = s.emotional_tone or "neutral"
        markers = ", ".join(s.ai_relationship_markers) if s.ai_relationship_markers else "none"
        line = (f"[{s.summary_date}] Topics: {topics} | Events: {events} | "
                f"Tone: {tone} | Markers: {markers}")
        scores = getattr(s, "behavioral_scores", None)
        if scores:
            top = max(scores.items(), key=lambda kv: kv[1])
            zone = getattr(s, "risk_zone", None) or "n/a"
            line += f" | Zone: {zone} | Peak: {top[0]} {top[1]:.2f}"
        lines.append(line)
    return "\n".join(lines)
```

- [ ] **Step 2: Smoke — render with and without scores**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -c "
import sys; sys.path.insert(0,'src')
from types import SimpleNamespace as N
from behavioral.behavioral_llm import _format_calendar
from datetime import date
thematic=N(summary_date=date(2026,3,1),key_topics=['work'],life_events=[],
           emotional_tone='anxious',ai_relationship_markers=[])
anchored=N(summary_date=date(2026,3,2),key_topics=['work'],life_events=[],
           emotional_tone='anxious',ai_relationship_markers=[],
           behavioral_scores={'decision_delegation':0.45,'topic_concentration':0.1},
           risk_zone='YELLOW')
print(_format_calendar([thematic]))
print('---')
print(_format_calendar([anchored]))
"
```

Expected: the first entry has no `Zone:`/`Peak:` suffix (production-safe), the second ends with `| Zone: YELLOW | Peak: decision_delegation 0.45`.

### Task 3.2: Carry scores+zone into the corpus calendar entry; add `--no-calendar`

**Files:**
- Modify: `experiments/evaluate_corpus.py:397-403` (calendar append)
- Modify: `experiments/evaluate_corpus.py:372` (Stage-3 call)
- Modify: `experiments/evaluate_corpus.py` `RunConfig` + arg parser (near lines 475 / 498)

- [ ] **Step 1: Add `behavioral_scores` and `risk_zone` to the calendar entry**

Replace the `calendar.append(SimpleNamespace(...))` block at `experiments/evaluate_corpus.py:397-403` with:

```python
            calendar.append(SimpleNamespace(
                summary_date=today,
                key_topics=summary.get("key_topics", []),
                life_events=summary.get("life_events", []),
                emotional_tone=summary.get("emotional_tone", "neutral"),
                ai_relationship_markers=summary.get("ai_relationship_markers", []),
                behavioral_scores=scores,
                risk_zone=zone,
            ))
```

- [ ] **Step 2: Add a `use_calendar` flag to `RunConfig` and the parser**

In the `RunConfig` dataclass (near `experiments/evaluate_corpus.py:475`), add a field:

```python
    use_calendar: bool = True
```

In the argument parser (near line 498 where other args are defined), add:

```python
    ap.add_argument("--no-calendar", dest="use_calendar", action="store_false",
                    help="E9 ablation: run Stage 3 with the calendar disabled")
```

and pass `use_calendar=args.use_calendar` into the `RunConfig(...)` construction.

- [ ] **Step 3: Honour the flag at the Stage-3 call site**

At `experiments/evaluate_corpus.py:372`, replace:

```python
        stage3 = await stage3_behavioral(today, s3_sessions, calendar[-14:], cfg)
```

with:

```python
        cal = calendar[-14:] if cfg.use_calendar else []
        stage3 = await stage3_behavioral(today, s3_sessions, cal, cfg)
```

- [ ] **Step 4: Smoke — `--no-calendar` runs and disables the calendar**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/evaluate_corpus.py --personas dmitry --limit-days 4 --no-calendar \
  --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://localhost:11434 \
  --stage3-model ollama_chat/gpt-oss:latest --stage3-api-base http://localhost:11434 \
  --temperature 0.0 2>&1 | tail -6
```

Expected: runs without error. (Calendar-disabled means each day is scored in isolation — the run itself just needs to complete cleanly.)

### Task 3.3: Update the Stage-3 prompt to anchor to the calendar

**Files:**
- Modify: `src/behavioral/behavioral_llm.py:72-77` (`calendar_block`)

- [ ] **Step 1: Strengthen the calendar instruction**

Replace the `calendar_block` assignment at `src/behavioral/behavioral_llm.py:72-77` with:

```python
        calendar_block = f"""
A CALENDAR of previous notable days is provided below. Each entry may carry the
prior day's risk Zone and its Peak behavioural score. ANCHOR today's scores to
this trend: if the calendar shows a sustained moderate level, today's scores
should stay near that level unless today's messages give a clear reason to move.
Do not swing a dimension from high to near-zero (or back) between adjacent days
without explicit evidence. Reference the calendar in operator_note using dates.

{calendar_section}
"""
```

- [ ] **Step 2: Smoke — prompt builds with the new block**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -c "
import sys; sys.path.insert(0,'src')
from behavioral.behavioral_llm import _build_prompt
from datetime import date
p=_build_prompt(date(2026,3,2),['hello'],'=== CALENDAR ===\n[x]')
assert 'ANCHOR today' in p, 'anchor instruction missing'
print('ok, prompt len', len(p))
"
```

Expected: `ok, prompt len <N>`.

### Task 3.4: Write the three-arm ablation driver

**Files:**
- Create: `experiments/stage3_calendar_ablation.py`

- [ ] **Step 1: Create `experiments/stage3_calendar_ablation.py`**

```python
#!/usr/bin/env python3
"""E9 — calendar on/off ablation. Runs the full corpus three ways under a fixed
model and persona split, scores each, and reports per-persona score stability
(the std of each dimension across a persona's days) plus zone metrics.

Arms:
  off       — calendar disabled (--no-calendar)
  thematic  — calendar on, thematic fields only (pre-E9 _format_calendar)
  anchored  — calendar on, score-anchored (post-E9 _format_calendar)

The 'thematic' arm is produced by git-stashing the E9 _format_calendar change;
this driver only orchestrates the 'off' and 'anchored' runs and the scoring."""
import argparse
import glob
import json
import os
import statistics
import subprocess

from optimize_thresholds import HERE
from recalibrate_stage2 import macro_f1

CORPUS = HERE / "results" / "corpus"
BASE = ["--generator", "qwen36",
        "--classifier-model", "ollama_chat/gpt-oss-safeguard:latest",
        "--classifier-api-base", "http://localhost:11434",
        "--stage3-model", "ollama_chat/gpt-oss:latest",
        "--stage3-api-base", "http://localhost:11434",
        "--temperature", "0.0"]


def newest_eval() -> str:
    return max(glob.glob(str(CORPUS / "*_corpus_eval.jsonl")), key=os.path.getmtime)


def run_arm(extra: list[str]) -> str:
    """Run evaluate_corpus.py and return the path of the eval file it produced."""
    subprocess.run(["python3", "-u", "experiments/evaluate_corpus.py", *BASE, *extra],
                   check=True, cwd=str(HERE.parent))
    return newest_eval()


def stability(path: str) -> dict:
    """Per-persona mean std of the 7 dims across that persona's days."""
    rows = [json.loads(l) for l in open(path) if l.strip()]
    by = {}
    for r in rows:
        by.setdefault(r["persona"], []).append(r["behavioral_scores"])
    out = {}
    for p, scores in by.items():
        keys = scores[0].keys()
        stds = [statistics.pstdev([s[k] for s in scores]) for k in keys if len(scores) > 1]
        out[p] = round(sum(stds) / len(stds), 4) if stds else 0.0
    return out


def zone_score(path: str) -> dict:
    rows = [json.loads(l) for l in open(path) if l.strip()]
    pairs = [(r["expected_zone"], r["predicted_zone"]) for r in rows]
    f1, fpr = macro_f1(pairs)
    match = sum(1 for e, p in pairs if e == p) / len(pairs)
    return {"zone_match": round(match, 3), "macro_f1": round(f1, 3),
            "fpr_green": round(fpr, 3)}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--off", help="path to a pre-run calendar-off eval file")
    ap.add_argument("--thematic", help="path to a pre-run thematic-calendar eval file")
    ap.add_argument("--anchored", help="path to a pre-run score-anchored eval file")
    args = ap.parse_args()

    arms = {}
    arms["off"] = args.off or run_arm(["--no-calendar"])
    arms["anchored"] = args.anchored or run_arm([])
    if args.thematic:
        arms["thematic"] = args.thematic

    report = {}
    for name, path in arms.items():
        report[name] = {"file": os.path.basename(path),
                        "zones": zone_score(path),
                        "stability_mean": round(
                            sum(stability(path).values()) / len(stability(path)), 4),
                        "stability_by_persona": stability(path)}
        z = report[name]["zones"]
        print(f"{name:9s}: zone_match={z['zone_match']}  macro_f1={z['macro_f1']}  "
              f"fpr_green={z['fpr_green']}  mean_score_std={report[name]['stability_mean']}")

    (HERE / "results" / "stage3_calendar_ablation.json").write_text(
        json.dumps(report, indent=2))
    print("wrote results/stage3_calendar_ablation.json")


if __name__ == "__main__":
    main()
```

- [ ] **Step 2: Produce the `thematic` arm (pre-E9 calendar) first**

The thematic arm needs the *old* `_format_calendar`. Before the E9 changes are committed, run it from a clean checkout of `behavioral_llm.py`:

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
git stash push src/behavioral/behavioral_llm.py   # temporarily drop E9 prompt+calendar edits
python3 -u experiments/evaluate_corpus.py --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://localhost:11434 \
  --stage3-model ollama_chat/gpt-oss:latest --stage3-api-base http://localhost:11434 \
  --temperature 0.0 > experiments/results/ablation_thematic.log 2>&1
git stash pop                                     # restore E9 edits
```

Record the produced eval file path as `THEMATIC_EVAL`.

> If `git stash` is undesirable because of the other uncommitted changes in the repo, instead commit the E9 edits first (gated), then check out the parent commit's `behavioral_llm.py` into a temp path and run with `PYTHONPATH` pointed at it. The stash approach is simpler when only `behavioral_llm.py` is restored.

- [ ] **Step 3: Run the `off` and `anchored` arms and score all three**

Sequential — one Ollama job at a time:

```bash
python3 -u experiments/stage3_calendar_ablation.py --thematic <THEMATIC_EVAL> \
  > experiments/results/stage3_calendar_ablation.log 2>&1
```

- [ ] **Step 4: Inspect the ablation report**

```bash
python3 -c "import json; print(json.dumps(json.load(open('experiments/results/stage3_calendar_ablation.json')),indent=2))" | head -40
```

Expected reading: `anchored` should show lower `mean_score_std` than `thematic` and `off` (the variance the calendar is meant to suppress), and zone metrics no worse. The honest outcomes:
- anchored stability ↑ **and** macro-F1 ↑ → score-anchoring works; adopt it.
- anchored stability ↑ but macro-F1 flat → the calendar stabilises scores but the threshold engine already absorbed the variance; report as a partial win.
- no stability change → the calendar digest is not being used by the model → candidate for E10 (model capacity).

- [ ] **Step 5: Commit (gated)**

```bash
git add src/behavioral/behavioral_llm.py experiments/evaluate_corpus.py experiments/stage3_calendar_ablation.py
git commit -m "feat: E9 score-anchored calendar + on/off ablation"
```

---

## Phase 4 — E10 (optional): Stage-3 model-swap smoke

Only if Phase 3 Step 4 showed no stability change. Decides whether the residual variance is model capacity.

### Task 4.1: Re-score three personas with a stronger Stage-3 model

**Files:** none modified — a parametrised run.

- [ ] **Step 1: Run viktor/sara/nastya with deepseek-v3.2 on RouterAI**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/evaluate_corpus.py --personas viktor,sara,nastya \
  --generator qwen36 \
  --classifier-model ollama_chat/gpt-oss-safeguard:latest --classifier-api-base http://localhost:11434 \
  --stage3-model openai/deepseek/deepseek-v3.2 --stage3-api-base https://routerai.ru/api/v1 \
  --temperature 0.0 > experiments/results/e10_model_swap.log 2>&1
```

(RouterAI Stage 3 + local Ollama Stage 2 is fine — only one job hits the GPU.)

- [ ] **Step 2: Compare per-dimension score std against the gpt-oss run**

```bash
python3 -c "
import json,glob,os,statistics
def stab(path,personas):
    rows=[json.loads(l) for l in open(path) if l.strip()]
    by={}
    for r in rows:
        if r['persona'] in personas: by.setdefault(r['persona'],[]).append(r['behavioral_scores'])
    for p,sc in by.items():
        ks=sc[0].keys()
        print(p, round(sum(statistics.pstdev([s[k] for s in sc]) for k in ks)/len(ks),4))
new=max(glob.glob('experiments/results/corpus/*_corpus_eval.jsonl'),key=os.path.getmtime)
print('deepseek-v3.2:'); stab(new,{'viktor','sara','nastya'})
"
```

Expected: a per-persona mean-std line. Markedly lower std than the gpt-oss baseline → variance is model capacity; recommend the stronger Stage-3 model in the chapter. Similar std → variance is intrinsic to the task framing, not the model.

- [ ] **Step 3: Record the finding**

Write the comparison into `results/e10_model_swap.json` (a small hand-written JSON: `{"model":"deepseek-v3.2","stability_by_persona":{...},"baseline_gpt_oss":{...},"verdict":"..."}`). No commit needed — this is a results artefact.

---

## Phase 5 — Stage-4 re-validation and document refresh

### Task 5.1: Re-confirm the Stage-4 optimum on the best upstream corpus

**Files:**
- Modify: `experiments/optimize_thresholds.py:48` (`BASELINE_FILES`)

- [ ] **Step 1: Point `BASELINE_FILES` at the winning corpus**

Set `BASELINE_FILES` to the single eval file from the best-performing arm (the E9 `anchored` run, or the E8b run if that won). Use the basename only.

- [ ] **Step 2: Re-run the threshold and hysteresis searches**

```bash
cd /home/newub/w/co/univer/Kursoviki/Sophiya/safe-llm/ai-safety-dev
python3 -u experiments/optimize_thresholds.py 2>&1 | tail -12
python3 -u experiments/hysteresis_experiment.py 2>&1 | tail -10
```

Expected: the optimum either holds (a robustness result) or shifts (the upstream fix changed what Stage 4 should do). Either is reportable — record the before/after.

- [ ] **Step 3: Commit (gated)**

```bash
git add experiments/optimize_thresholds.py
git commit -m "chore: re-validate Stage-4 optimum on upstream-repaired corpus"
```

### Task 5.2: Refresh the three deliverable documents

**Files:**
- Modify: `experiments/results/chapter4-results.md`
- Modify: `Sophiya/2026-05-13-draft4/chapter4-draft.md`
- Modify: `Sophiya/safe-llm/docs/chapter4-experiments-for-sonya.md`

- [ ] **Step 1: Update `chapter4-results.md`**

Add an E8/E9/E10 results section: the E8a recalibration table, the E8b graded-prompt deltas, the E9 three-arm calendar ablation table (off/thematic/anchored — zone metrics + mean score std), and the E10 verdict if run. Drop any stale dmitry-13/17 · rina-6/10 coverage caveat.

- [ ] **Step 2: Rewrite the §4.8 "two directions" passage in `chapter4-draft.md`**

The draft's §4.8 currently names DSPy E1 as the residual Stage-3 fix. Replace that with: E1 established as a no-op (cite the 80.0→80.0 / Δ0.0 table); the residual was relocated upstream; E8 repaired Stage 2 and E9 tested the longitudinal calendar. Keep Sonya's voice — address the reader as «Вы», do not enumerate ГОСТ rules, normalise the negative results as findings. Do not number the new subsections.

- [ ] **Step 3: Update `chapter4-experiments-for-sonya.md`**

Mark E1 done (negative), E7 skipped (redundant), and add E8/E9/E10 with their methods and outcomes in the same student-facing register as the existing entries.

- [ ] **Step 4: Commit (gated)**

```bash
git add experiments/results/chapter4-results.md \
        ../2026-05-13-draft4/chapter4-draft.md \
        docs/chapter4-experiments-for-sonya.md
git commit -m "docs: chapter 4 — E8/E9 upstream YELLOW-repair results"
```

---

## Self-review notes

- **Spec coverage:** E8a → Phase 1; E8b → Phase 2; E9 + calendar ablation → Phase 3; E10 → Phase 4; raw-predict persistence prerequisite → Phase 0; Stage-4 re-validation → Phase 5.1; E1 preservation → done pre-plan (annotated JSON) + Phase 5.2 Step 2. All design sections map to a task.
- **No pytest:** the harness has no test suite; verification is smoke runs + JSON inspection, matching the repo's `--smoke`/`results/*.json` pattern. This is a deliberate deviation from the skill's pytest-TDD default, justified by the existing codebase.
- **Open construction detail:** `rerun_stage2.py`'s `RunConfig(...)` keyword arguments must be reconciled with the actual dataclass in `evaluate_corpus.py` — flagged inline in Task 2.2.
- **Commit gating:** every commit step is explicitly gated on user approval; no `git add -A`; pre-existing unrelated uncommitted changes are never staged by this plan.
