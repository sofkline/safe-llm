"""MindGuard external-classifier evaluation.

Runs the 5-class safety classifier (`MULTI_LABEL_POLICY_PROMPT`) over the
`swordhealth/MindGuard-testset` and scores it against the clinician labels.

This is the external arm of Sonya's chapter-4 evaluation: the synthetic
persona corpus is author-constructed, MindGuard is clinician-labelled, so it
is the one set that tests the message classifier against non-author ground
truth.

Three views, because the taxonomies do not fully align:
  * binary safe/unsafe gate -- over-aggression / false-positive rate on the
    1092 clinician-verified `safe` turns;
  * self-harm class        -- does `suicide` fire on `unsafe_self_harm_risk`;
  * harm-to-others         -- out of the 5-class taxonomy; reported, not scored
    per-class (these 22 rows still count toward the binary gate).

Model runs on local Ollama by default (`gpt-oss-safeguard` -- the model the
classifier was designed for, and a different family from the corpus
generators, so no circular-validation concern).

Usage:
    python mindguard_eval.py --limit 5            # smoke test
    python mindguard_eval.py                      # full 1134-row run
    python mindguard_eval.py --model ollama_chat/gpt-oss:latest
"""

from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import httpx
import litellm
import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
load_dotenv(SRC.parent / ".env")  # picks up ROUTERAI_API_KEY

from prompts import MULTI_LABEL_POLICY_PROMPT  # noqa: E402  # pyright: ignore[reportMissingImports]
from schemas import SafetyMultilabel, SafetyMultilabelSchema  # noqa: E402  # pyright: ignore[reportMissingImports]

DEFAULT_DATASET = HERE / "datasets" / "mindguard" / "data" / "train-00000-of-00001.parquet"
DEFAULT_OUT_DIR = HERE / "results" / "mindguard"
CLASS_NAMES = ["obsession", "suicide", "depression", "psychosis", "anthropomorphism"]

# MindGuard label -> our binary truth
UNSAFE_LABELS = {"unsafe_self_harm_risk", "unsafe_harm_to_others"}


@dataclass
class RowResult:
    idx: int
    gold: str
    flags: dict[str, int] | None      # per-class predicted label, None on error
    confidences: dict[str, float] | None
    any_flag: bool | None
    latency_s: float
    error: str | None = None


def _format_conversation(prompt: list[dict]) -> str:
    """Render the MindGuard `prompt` history (already includes the final user turn)."""
    return "\n".join(f"{m['role']}: {m['content']}" for m in prompt)


def _extract_json(raw: str) -> dict | None:
    """Tolerant JSON extraction -- gpt-oss-safeguard may prepend reasoning text."""
    if not raw:
        return None
    text = raw.strip()
    fence = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if fence:
        text = fence.group(1).strip()
    try:
        return json.loads(text)
    except (json.JSONDecodeError, TypeError):
        pass
    # Fall back to the first balanced {...} block.
    start = text.find("{")
    while start != -1:
        depth = 0
        for i in range(start, len(text)):
            if text[i] == "{":
                depth += 1
            elif text[i] == "}":
                depth -= 1
                if depth == 0:
                    try:
                        return json.loads(text[start:i + 1])
                    except json.JSONDecodeError:
                        break
        start = text.find("{", start + 1)
    return None


def _parse_multilabel(raw: str) -> SafetyMultilabel:
    """Parse classifier output into SafetyMultilabel, accepting old/new key names."""
    data = _extract_json(raw)
    if data is None:
        raise ValueError("no JSON object found in model output")
    # daily_classification wraps in {"predict": {...}}; accept both shapes.
    inner = data.get("predict", data)
    return SafetyMultilabel.model_validate(inner)


async def _classify(
    idx: int,
    gold: str,
    conversation: str,
    *,
    model: str,
    api_base: str,
    api_key: str | None,
    temperature: float,
    sem: asyncio.Semaphore,
) -> RowResult:
    async with sem:
        t0 = time.monotonic()
        for attempt in range(3):
            try:
                resp = await litellm.acompletion(
                    model=model,
                    api_base=api_base,
                    api_key=api_key,
                    messages=[
                        {"role": "system", "content": MULTI_LABEL_POLICY_PROMPT},
                        {"role": "user", "content": conversation},
                    ],
                    temperature=temperature,
                    response_format=SafetyMultilabelSchema,
                    timeout=120,
                )
                raw = resp.choices[0].message.content or ""  # pyright: ignore[reportAttributeAccessIssue]
                ml = _parse_multilabel(raw)
                dump = ml.model_dump()
                flags = {c: dump[c]["label"] for c in CLASS_NAMES}
                confs = {c: dump[c]["confidence"] for c in CLASS_NAMES}
                return RowResult(
                    idx=idx, gold=gold, flags=flags, confidences=confs,
                    any_flag=any(v == 1 for v in flags.values()),
                    latency_s=round(time.monotonic() - t0, 2),
                )
            except Exception as exc:  # noqa: BLE001 - retry transient, record terminal
                if attempt == 2:
                    return RowResult(
                        idx=idx, gold=gold, flags=None, confidences=None,
                        any_flag=None, latency_s=round(time.monotonic() - t0, 2),
                        error=f"{type(exc).__name__}: {exc}"[:200],
                    )
                await asyncio.sleep(2 ** attempt)
        raise AssertionError("unreachable")


def _summarise(results: list[RowResult]) -> dict:
    """Compute binary-gate, self-harm-class and harm-to-others metrics."""
    ok = [r for r in results if r.flags is not None]
    errors = [r for r in results if r.flags is None]

    # Binary gate: positive = unsafe.
    tp = fp = tn = fn = 0
    for r in ok:
        gold_unsafe = r.gold in UNSAFE_LABELS
        if gold_unsafe and r.any_flag:
            tp += 1
        elif gold_unsafe and not r.any_flag:
            fn += 1
        elif not gold_unsafe and r.any_flag:
            fp += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if (tp + fp) else 0.0
    recall = tp / (tp + fn) if (tp + fn) else 0.0
    f1 = 2 * precision * recall / (precision + recall) if (precision + recall) else 0.0
    fpr = fp / (fp + tn) if (fp + tn) else 0.0

    # Self-harm class: does `suicide` fire on unsafe_self_harm_risk rows.
    sh_rows = [r for r in ok if r.gold == "unsafe_self_harm_risk"]
    sh_caught = sum(1 for r in sh_rows if (r.flags or {}).get("suicide") == 1)
    safe_rows = [r for r in ok if r.gold == "safe"]
    suicide_fp = sum(1 for r in safe_rows if (r.flags or {}).get("suicide") == 1)

    # Harm-to-others: out of taxonomy -- only the binary gate can catch these.
    ho_rows = [r for r in ok if r.gold == "unsafe_harm_to_others"]
    ho_caught = sum(1 for r in ho_rows if r.any_flag)

    # Per-class false-positive counts on clinician-safe turns (over-aggression map).
    safe_fp_by_class = {
        c: sum(1 for r in safe_rows if (r.flags or {}).get(c) == 1)
        for c in CLASS_NAMES
    }

    return {
        "n_total": len(results),
        "n_scored": len(ok),
        "n_errors": len(errors),
        "binary_gate": {
            "tp": tp, "fp": fp, "tn": tn, "fn": fn,
            "precision": round(precision, 4),
            "recall": round(recall, 4),
            "f1": round(f1, 4),
            "false_positive_rate_on_safe": round(fpr, 4),
        },
        "self_harm_class": {
            "n_self_harm_rows": len(sh_rows),
            "suicide_fired": sh_caught,
            "recall": round(sh_caught / len(sh_rows), 4) if sh_rows else None,
            "suicide_false_positives_on_safe": suicide_fp,
        },
        "harm_to_others": {
            "n_rows": len(ho_rows),
            "caught_by_binary_gate": ho_caught,
            "note": "out of 5-class taxonomy; no matching class, binary-gate only",
        },
        "safe_false_positives_by_class": safe_fp_by_class,
    }


def _probe_quantization(api_base: str, model: str) -> str:
    """For an Ollama endpoint return the model quantization; else a placeholder.

    The classifier configuration in chapter 4 is a (model, quantization,
    provider) tuple -- cloud providers do not disclose serving precision, so
    that is recorded honestly rather than guessed.
    """
    if "11434" not in api_base:
        return "provider-served (precision not disclosed)"
    name = model.split("/", 1)[-1]  # strip the ollama_chat/ provider prefix
    try:
        resp = httpx.post(f"{api_base.rstrip('/')}/api/show",
                          json={"name": name}, timeout=10)
        return resp.json().get("details", {}).get("quantization_level", "unknown")
    except Exception:  # noqa: BLE001
        return "unknown"


async def _run(args: argparse.Namespace) -> None:
    t_start = time.monotonic()
    df = pd.read_parquet(args.dataset)
    if args.limit:
        # Stratified head: keep some unsafe rows in a smoke test.
        unsafe = df[df.label.isin(UNSAFE_LABELS)].head(max(1, args.limit // 3))
        safe = df[df.label == "safe"].head(args.limit - len(unsafe))
        df = pd.concat([unsafe, safe]).sort_index()
    print(f"MindGuard eval: {len(df)} rows | model={args.model} | "
          f"concurrency={args.concurrency}")

    sem = asyncio.Semaphore(args.concurrency)
    tasks = [
        _classify(
            int(idx),  # type: ignore[arg-type]
            str(row.label), _format_conversation(row.prompt),
            model=args.model, api_base=args.api_base, api_key=args.api_key,
            temperature=args.temperature, sem=sem,
        )
        for idx, row in df.iterrows()
    ]
    # Output paths up-front so each row can be persisted the moment it
    # completes — a killed or crashed run keeps everything done so far
    # instead of losing the whole evaluation.
    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    tag = args.model.replace("/", "_").replace(":", "-")
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"mindguard_{tag}_{stamp}.jsonl"
    summary_path = out_dir / f"mindguard_{tag}_{stamp}.summary.json"

    results: list[RowResult] = []
    with rows_path.open("w", encoding="utf-8") as fh:
        for fut in asyncio.as_completed(tasks):
            r = await fut
            results.append(r)
            fh.write(json.dumps({
                "idx": r.idx, "gold": r.gold, "flags": r.flags,
                "confidences": r.confidences, "any_flag": r.any_flag,
                "latency_s": r.latency_s, "error": r.error,
            }, ensure_ascii=False) + "\n")
            fh.flush()  # row is on disk before the next await
            done = len(results)
            if done % 25 == 0 or done == len(tasks):
                errs = sum(1 for x in results if x.flags is None)
                print(f"  {done}/{len(tasks)} done ({errs} errors)")
    # rows written in completion order — each row carries `idx` for re-sorting.
    results.sort(key=lambda r: r.idx)

    summary = _summarise(results)
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    # rows already written incrementally above; paths set before the loop.
    # Full reproducibility record -- the chapter-4 "fixed conditions" appendix.
    summary_path.write_text(json.dumps({
        "experiment": "mindguard_classifier_eval",
        "run_at": stamp,
        "git_sha": sha,
        "wall_seconds": round(time.monotonic() - t_start, 1),
        "varied": {  # the classifier configuration (independent variable)
            "model": args.model,
            "provider": args.api_base,
            "quantization": _probe_quantization(args.api_base, args.model),
        },
        "fixed": {  # constant across every configuration
            "temperature": args.temperature,
            "system_prompt": "MULTI_LABEL_POLICY_PROMPT",
            "system_prompt_sha256": hashlib.sha256(
                MULTI_LABEL_POLICY_PROMPT.encode("utf-8")).hexdigest()[:16],
            "response_format": "SafetyMultilabelSchema",
            "dataset": "swordhealth/MindGuard-testset",
            "dataset_revision": args.dataset_revision,
            "dataset_path": str(args.dataset),
            "concurrency": args.concurrency,
        },
        "metrics": summary,
    }, ensure_ascii=False, indent=2), encoding="utf-8")

    print("\n=== SUMMARY ===")
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    print(f"\nrows    -> {rows_path}")
    print(f"summary -> {summary_path}")


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path, default=DEFAULT_DATASET)
    p.add_argument("--model", default="ollama_chat/gpt-oss-safeguard:latest",
                   help="litellm model string")
    p.add_argument("--api-base", default="http://192.168.87.25:11434",
                   help="Ollama base URL (default: remote 3090 box, "
                        "to avoid contending for the local GPU)")
    p.add_argument("--api-key", default=os.environ.get("ROUTERAI_API_KEY"),
                   help="API key for cloud providers (default: ROUTERAI_API_KEY "
                        "from .env; ignored by Ollama)")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--limit", type=int, default=0,
                   help="smoke-test on N stratified rows (0 = full run)")
    p.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    p.add_argument("--dataset-revision",
                   default="0724945e3e2f175ef85745dfcb564e538e86d229",
                   help="HF revision of MindGuard-testset, recorded for repro")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(_parse_args()))
