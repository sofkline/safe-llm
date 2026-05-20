"""End-to-end pipeline evaluation on MindGuard's clinician-safe conversations.

External-specificity test for chapter 4: take MindGuard rows where every
turn is clinician-labelled `safe`, treat each conversation as a synthetic
"day" of K sessions, and run the full Stage 1 → 2 → 3 → 4 pipeline on it.

The pipeline's specificity claim is "Stage 4 rests at GREEN on benign
interactions". With MindGuard supplying non-author ground truth, this is
the only externally-valid specificity number the chapter can cite.

Mapping (Design (ii) from 2026-05-20 design discussion):
  one MindGuard conversation = one day with K sessions
  K = 3 if conversation has >= 6 turn-pairs, else 1
  sessions placed at hours [10, 14, 20] (no night, no extreme bursts)
  Stage 1 timestamps synthesised with 5-min gap between user messages
  calendar starts empty (each conversation is its own one-day synthetic user)

Outputs:
  results/mindguard/pipeline_<sha>_<stamp>.jsonl     one row per conversation
  results/mindguard/pipeline_<sha>_<stamp>.summary.json

Usage:
  python mindguard_pipeline.py --limit 5    # smoke
  python mindguard_pipeline.py              # full ~98-conversation safe set
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pandas as pd
from dotenv import load_dotenv

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))
load_dotenv(SRC.parent / ".env")

import evaluate_corpus as ec  # noqa: E402
from behavioral.temporal import compute_baselines  # noqa: E402  # pyright: ignore[reportMissingImports]
from behavioral.risk_engine import evaluate_risk_zone  # noqa: E402  # pyright: ignore[reportMissingImports]


SESSION_HOURS_K1 = [14]
SESSION_HOURS_K3 = [10, 14, 20]
SESSION_GAP_MIN = 5.0  # gap between user messages within a session


def _factor_conversations(df: pd.DataFrame):
    """Group rows by the first 2 turns of their `prompt` (stable per dialogue)."""
    def key(p):
        head = p[:2] if len(p) >= 2 else p
        return tuple((m["role"], m["content"]) for m in head)
    codes, _ = pd.factorize(df.prompt.apply(key))
    return codes


def _select_conversations(df: pd.DataFrame, filt: str) -> list[dict]:
    """Return one row per conversation matching `filt`.

    filt = "safe":   conversation has every turn labelled clinician-safe.
    filt = "unsafe": conversation contains at least one clinician-unsafe turn
                    (unsafe_self_harm_risk or unsafe_harm_to_others).

    Picks the row with the longest `prompt` from each matching conversation
    — that row contains the full conversational history. Also returns the
    label mix so downstream code can compute sensitivity.
    """
    df = df.copy()
    df["_conv"] = _factor_conversations(df)
    if filt == "safe":
        convs = (
            df.groupby("_conv")
            .filter(lambda g: (g.label == "safe").all())
            ._conv.unique()
        )
    elif filt == "unsafe":
        convs = (
            df.groupby("_conv")
            .filter(lambda g: (g.label != "safe").any())
            ._conv.unique()
        )
    else:
        raise ValueError(f"unknown filter: {filt}")
    out = []
    for c in sorted(convs):
        rows = df[df._conv == c]
        longest = rows.loc[rows.prompt.apply(len).idxmax()]
        label_mix = dict(rows.label.value_counts())
        out.append({
            "conv_id": int(c),
            "n_turns": len(longest.prompt),
            "n_rows_in_conv": len(rows),
            "label_mix": label_mix,
            "prompt": list(longest.prompt),
        })
    return out




def _pair_turns(prompt: list[dict]) -> list[dict]:
    """Pair adjacent (user, assistant) turns from a MindGuard prompt.

    A MindGuard prompt is a list of {role, content} dicts ending on a user
    turn. We pair user→assistant; a trailing user turn becomes a half-pair
    (assistant text empty) — the pipeline only samples user messages so
    this is fine for Stage 1/3, and Stage 2 sees the User: line.
    """
    pairs = []
    i = 0
    while i < len(prompt):
        m = prompt[i]
        if m["role"] != "user":
            i += 1
            continue
        user = m["content"]
        assistant = ""
        if i + 1 < len(prompt) and prompt[i + 1]["role"] == "assistant":
            assistant = prompt[i + 1]["content"]
            i += 2
        else:
            i += 1
        pairs.append({"user": user, "assistant": assistant})
    return pairs


def _build_day_sessions(prompt: list[dict]) -> list[dict]:
    """Map one conversation to a list of safe-llm session dicts.

    K=3 sessions if >=6 user-assistant pairs, else K=1. Pairs split evenly
    across sessions. Each session uses the safe-llm session schema
    (day=1, session_hour, exchanges, phase).
    """
    pairs = _pair_turns(prompt)
    if not pairs:
        return []
    K = 3 if len(pairs) >= 6 else 1
    hours = SESSION_HOURS_K3 if K == 3 else SESSION_HOURS_K1
    # Even split
    sizes = [len(pairs) // K] * K
    for i in range(len(pairs) % K):
        sizes[i] += 1
    sessions = []
    cursor = 0
    for hour, sz in zip(hours, sizes):
        chunk = pairs[cursor:cursor + sz]
        cursor += sz
        if not chunk:
            continue
        sessions.append({
            "day": 1,
            "session_hour": hour,
            "phase": "mindguard_safe",
            "exchanges": chunk,
        })
    return sessions


def _synth_timestamps(day: int, session: dict, gap_min: float) -> list[datetime]:
    """Synthesise one timestamp per user message in a session. Mirrors
    evaluate_corpus.synth_timestamps but doesn't need persona_cfg."""
    base = datetime.combine(ec.EPOCH + timedelta(days=day - 1), datetime.min.time())
    base = base.replace(hour=int(session["session_hour"]))
    n = len(session["exchanges"])
    return [base + timedelta(minutes=i * gap_min) for i in range(n)]


def _make_stage3_sessions(day_sessions: list[dict]) -> list[dict]:
    """Build Stage-3 session dicts without persona_cfg gap lookups."""
    sessions = []
    for s in day_sessions:
        ts = _synth_timestamps(s["day"], s, SESSION_GAP_MIN)
        user_msgs = [ex["user"] for ex in s["exchanges"] if ex.get("user")]
        total = len(user_msgs)
        sampled = user_msgs if total <= 5 else user_msgs[:3] + user_msgs[-2:]
        sessions.append({
            "start": ts[0], "end": ts[-1] if ts else ts[0],
            "messages": sampled, "total": total,
        })
    sessions.sort(key=lambda x: x["start"])
    return sessions


async def _evaluate_conversation(conv: dict, cfg: ec.RunConfig) -> dict:
    """Run the full pipeline on one conversation. Returns a result dict."""
    day_sessions = _build_day_sessions(conv["prompt"])
    if not day_sessions:
        return {"conv_id": conv["conv_id"], "error": "no user turns"}

    today = ec.EPOCH

    # Stage 1
    ts_rows: list[tuple[datetime, str]] = []
    for s in day_sessions:
        stamps = _synth_timestamps(s["day"], s, SESSION_GAP_MIN)
        for ts, ex in zip(stamps, s["exchanges"]):
            if ex.get("user"):
                ts_rows.append((ts, ex["user"]))
    ts_rows.sort(key=lambda r: r[0])
    temporal = ec.stage1_temporal(ts_rows)

    baselines = compute_baselines([])  # no history — single-day synthetic user

    # Stage 2
    danger, n_failed, danger_raw = await ec.stage2_danger(day_sessions, cfg)

    # Stage 3
    s3_sessions = _make_stage3_sessions(day_sessions)
    stage3 = await ec.stage3_behavioral(today, s3_sessions, calendar=[], cfg=cfg)
    scores = stage3["scores"]
    summary = stage3["summary"]

    # Stage 4
    zone, triggers = await evaluate_risk_zone(
        temporal, danger, scores,
        baselines=baselines, recent_history=[],
        context={"persona": f"mindguard_safe_{conv['conv_id']}",
                 "date": today.isoformat(), "day": 1},
    )

    return {
        "conv_id": conv["conv_id"],
        "n_turns": conv["n_turns"],
        "n_rows_in_conv": conv["n_rows_in_conv"],
        "n_sessions": len(day_sessions),
        "n_classifier_failed": n_failed,
        "predicted_zone": zone,
        "triggered_rules": triggers,
        "temporal_metrics": temporal,
        "danger_class_agg": danger,
        "danger_predicts_raw": danger_raw,
        "behavioral_scores": scores,
        "behavioral_summary": summary,
    }


def _build_cfg(args) -> ec.RunConfig:
    """Build a RunConfig per backend. `local` uses two different Ollama models
    (gpt-oss-safeguard for Stage 2 + gpt-oss for Stage 3) — matches the
    original chapter-4 baseline E8 configuration; the other backends use one
    cloud model for both stages."""
    if args.backend == "local":
        api_base = args.api_base or "http://localhost:11434"
        return ec.RunConfig(
            corpus_dir=HERE / "results" / "pilot",  # unused but required
            generator="mindguard",
            classifier_model="ollama_chat/gpt-oss-safeguard:latest",
            classifier_api_base=api_base,
            classifier_api_key="ollama",
            stage3_model="ollama_chat/gpt-oss:latest",
            stage3_api_base=api_base,
            stage3_api_key="ollama",
            temperature=args.temperature,
            limit_days=None,
            use_calendar=False,
        )

    backends = {
        "openrouter": dict(
            model="openrouter/openai/gpt-oss-120b",
            api_base="",
            key_env="OPENROUTER_API_KEY",
        ),
        "routerai": dict(
            # gpt-oss-120b mirrors the E10 / openrouter config so the cloud arm
            # of this experiment is apples-to-apples; deepseek/deepseek-v3.2
            # also available on routerai if we want the E8/E9 config later.
            model="openai/openai/gpt-oss-120b",
            api_base="https://routerai.ru/api/v1",
            key_env="ROUTERAI_API_KEY",
        ),
    }
    b = backends[args.backend]
    key = os.environ.get(b["key_env"])
    if not key:
        raise SystemExit(f"{b['key_env']} not set")
    return ec.RunConfig(
        corpus_dir=HERE / "results" / "pilot",  # unused but required
        generator="mindguard",
        classifier_model=b["model"],
        classifier_api_base=b["api_base"],
        classifier_api_key=key,
        stage3_model=b["model"],
        stage3_api_base=b["api_base"],
        stage3_api_key=key,
        temperature=args.temperature,
        limit_days=None,
        use_calendar=False,
    )


async def _run(args: argparse.Namespace) -> None:
    t_start = time.monotonic()
    df = pd.read_parquet(args.dataset)
    convs = _select_conversations(df, args.filter)
    if args.limit:
        convs = convs[:args.limit]
    print(f"MindGuard pipeline eval: {len(convs)} {args.filter} conversations | "
          f"backend={args.backend} | temp={args.temperature}")

    cfg = _build_cfg(args)

    stamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    try:
        sha = subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"], cwd=HERE, text=True
        ).strip()
    except Exception:  # noqa: BLE001
        sha = "unknown"
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rows_path = out_dir / f"pipeline_{args.backend}_{args.filter}_{sha}_{stamp}.jsonl"
    summary_path = out_dir / f"pipeline_{args.backend}_{args.filter}_{sha}_{stamp}.summary.json"

    sem = asyncio.Semaphore(args.concurrency)

    async def _bounded(c):
        async with sem:
            return await _evaluate_conversation(c, cfg)

    def _write_summary(results: list[dict], *, partial: bool, elapsed: float) -> None:
        results_sorted = sorted(results, key=lambda r: r.get("conv_id", -1))
        zones = [r.get("predicted_zone") for r in results_sorted if "predicted_zone" in r]
        summary = {
            "experiment": "mindguard_pipeline_specificity",
            "run_at": stamp,
            "git_sha": sha,
            "wall_seconds": round(elapsed, 1),
            "partial": partial,
            "n_target": len(convs),
            "varied": {
                "backend": args.backend,
                "classifier_model": cfg.classifier_model,
                "stage3_model": cfg.stage3_model,
                "session_split": "K=3 if n_pairs>=6 else K=1",
                "session_hours_k3": SESSION_HOURS_K3,
                "session_hours_k1": SESSION_HOURS_K1,
            },
            "fixed": {
                "temperature": args.temperature,
                "dataset": "swordhealth/MindGuard-testset",
                "filter": (
                    "conversations where every labelled turn is clinician-safe"
                    if args.filter == "safe"
                    else "conversations containing at least one clinician-unsafe turn"
                ),
                "filter_name": args.filter,
                "calendar": "empty (one synthetic day per conversation)",
                "session_gap_min": SESSION_GAP_MIN,
            },
            "metrics": {
                "n_total": len(results_sorted),
                "n_scored": len(zones),
                "n_errors": len(results_sorted) - len(zones),
                "zone_counts": {
                    "GREEN": zones.count("GREEN"),
                    "YELLOW": zones.count("YELLOW"),
                    "RED": zones.count("RED"),
                },
                "specificity_rate_green": round(zones.count("GREEN") / len(zones), 4)
                                           if zones else None,
            },
        }
        summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                encoding="utf-8")
        label = "PARTIAL SUMMARY" if partial else "SUMMARY"
        print(f"\n=== {label} ===")
        print(json.dumps(summary["metrics"], ensure_ascii=False, indent=2))
        print(f"\nrows    -> {rows_path}")
        print(f"summary -> {summary_path}")

    results: list[dict] = []
    interrupted = False
    tasks: list[asyncio.Task] = []
    with rows_path.open("w", encoding="utf-8") as fh:
        try:
            tasks = [asyncio.create_task(_bounded(c)) for c in convs]
            for fut in asyncio.as_completed(tasks):
                r = await fut
                results.append(r)
                fh.write(json.dumps(r, ensure_ascii=False, default=str) + "\n")
                fh.flush()
                done = len(results)
                if done % 10 == 0 or done == len(convs):
                    zones = [x.get("predicted_zone") for x in results]
                    print(f"  {done}/{len(convs)} | "
                          f"GREEN={zones.count('GREEN')} "
                          f"YELLOW={zones.count('YELLOW')} "
                          f"RED={zones.count('RED')}",
                          flush=True)
        except (KeyboardInterrupt, asyncio.CancelledError):
            interrupted = True
            print(f"\n!! interrupted after {len(results)}/{len(convs)} conversations — "
                  f"cancelling in-flight tasks and writing partial summary",
                  flush=True)
            for t in tasks:
                if not t.done():
                    t.cancel()
            # let cancellations propagate so the event loop can clean up
            try:
                await asyncio.gather(*tasks, return_exceptions=True)
            except Exception:  # noqa: BLE001
                pass
    _write_summary(results, partial=interrupted,
                   elapsed=time.monotonic() - t_start)
    if interrupted:
        raise SystemExit(130)  # standard SIGINT exit code


def _parse_args() -> argparse.Namespace:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--dataset", type=Path,
                   default=HERE / "datasets" / "mindguard" / "data" / "train-00000-of-00001.parquet")
    p.add_argument("--backend", choices=["openrouter", "routerai", "local"],
                   default="openrouter",
                   help="openrouter=gpt-oss-120b (E10 config); "
                        "routerai=deepseek-v3.2 (E8/E9 config); "
                        "local=gpt-oss-safeguard (Stage 2) + gpt-oss (Stage 3) via Ollama")
    p.add_argument("--api-base", default=None,
                   help="Override the Ollama base URL when --backend=local "
                        "(default http://localhost:11434)")
    p.add_argument("--temperature", type=float, default=0.0)
    p.add_argument("--concurrency", type=int, default=4)
    p.add_argument("--filter", choices=["safe", "unsafe"], default="safe",
                   help="safe=specificity test (98 entirely-safe convs); "
                        "unsafe=sensitivity test (17 convs containing >=1 unsafe turn)")
    p.add_argument("--limit", type=int, default=0,
                   help="smoke-test on N conversations (0 = full filtered set)")
    p.add_argument("--out-dir", type=Path,
                   default=HERE / "results" / "mindguard")
    return p.parse_args()


if __name__ == "__main__":
    asyncio.run(_run(_parse_args()))
