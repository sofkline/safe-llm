#!/usr/bin/env python3
"""evaluate_corpus.py — run the synthetic persona corpus through the 4-stage
behavioral-monitoring pipeline and emit the "persona x day -> zone" table.

This is the §4.3-4.5 harness (experiments E2-E7 in chapter4-experiment-plan.md).
It reuses the production pipeline's pure logic — Stage-1 metric formulas,
Stage-2 `_aggregate_predictions`, the Stage-3 prompt builder/parser, and the
Stage-4 `evaluate_risk_zone` rule engine — and only replaces the DB
data-access layer with reads from the corpus JSONL. The pipeline code is NOT
re-implemented; only the "where the data comes from" layer is.

Per-day-point it produces: expected_zone (from the persona DayScript) vs
predicted_zone (from the pipeline), plus the full metric tuple. Output mirrors
mindguard_eval.py: a per-row JSONL + a self-documenting summary.json carrying
the varied/fixed reproducibility block.

Differences from the live pipeline, disclosed for §4.2:
  - data source: corpus JSONL instead of SpendLogs/PredictTable/DailySummary;
  - per-message timestamps are synthesised from DayScript session_hour +
    inter_msg_gap_min (the corpus stores no per-message timestamps);
  - temperature is forced to 0 for repeatability (live pipeline uses 0.1);
  - one pass per run — repeated-run dispersion (E5) = run this N times.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import subprocess
import sys
import time
from collections import defaultdict
from datetime import date, datetime, timedelta
from pathlib import Path
from types import SimpleNamespace

HERE = Path(__file__).resolve().parent
SRC = HERE.parent / "src"
sys.path.insert(0, str(SRC))
sys.path.insert(0, str(HERE))

from dotenv import load_dotenv  # noqa: E402

load_dotenv(SRC.parent / ".env")
# Importing behavioral.* transitively constructs config.Settings(), which
# requires DB/Langfuse vars. The harness reads the corpus from disk and never
# touches the DB or Langfuse (create_async_engine does not connect at import),
# so dummy values are safe wherever .env does not supply them.
for _k, _v in {
    "API_BASE_URL": "http://localhost:11434", "API_KEY": "none",
    "DB_NAME": "x", "DB_USER": "x", "DB_PASSWORD": "x",
    "DB_HOST": "localhost", "DB_PORT": "5432",
    "LANGFUSE_SECRET_KEY": "x", "LANGFUSE_PUBLIC_KEY": "x",
    "LANGFUSE_API_HOST": "http://localhost:3000",
}.items():
    os.environ.setdefault(_k, _v)

import litellm  # noqa: E402

from behavioral.danger_agg import _aggregate_predictions  # noqa: E402
from behavioral.behavioral_llm import (  # noqa: E402
    _build_prompt,
    _format_calendar,
    _parse_llm_response,
    _default_result,
)
from behavioral.risk_engine import evaluate_risk_zone  # noqa: E402
from behavioral.temporal import compute_baselines  # noqa: E402
from prompts import MULTI_LABEL_POLICY_PROMPT  # noqa: E402
from schemas import SafetyMultilabelSchema  # noqa: E402
from synthetic.personas import ALL_PERSONAS  # noqa: E402

NIGHT_HOURS = {1, 2, 3, 4, 5}
EPOCH = date(2025, 1, 1)
DEFAULT_CORPUS = HERE / "results" / "pilot"
DEFAULT_OUT_DIR = HERE / "results" / "corpus"


# ─────────────────────────────────────────────────────────────────────────────
# Corpus loading
# ─────────────────────────────────────────────────────────────────────────────

def load_persona_corpus(corpus_dir: Path, persona: str, generator: str) -> dict[int, list[dict]]:
    """Load one persona's sessions, grouped by day.

    Reads every `*<generator>*.edited.jsonl` under results/pilot/<persona>/.
    Resume runs and re-runs are de-duplicated by (day, session_hour): the line
    from the lexically-largest filename (latest timestamp) wins.

    Returns {day: [session_line, ...]} with sessions ordered by session_hour.
    """
    pdir = corpus_dir / persona
    files = sorted(p for p in pdir.glob("*.edited.jsonl") if generator in p.name)
    if not files:
        raise FileNotFoundError(
            f"No '*{generator}*.edited.jsonl' files for persona '{persona}' in {pdir}"
        )

    by_key: dict[tuple[int, int], dict] = {}
    for fp in files:  # ascending name order → later files overwrite earlier
        for raw in fp.read_text(encoding="utf-8").splitlines():
            raw = raw.strip()
            if not raw:
                continue
            line = json.loads(raw)
            if not line.get("exchanges"):
                continue
            by_key[(int(line["day"]), int(line["session_hour"]))] = line

    by_day: dict[int, list[dict]] = defaultdict(list)
    for (day, _), line in by_key.items():
        by_day[day].append(line)
    for day in by_day:
        by_day[day].sort(key=lambda s: s["session_hour"])
    return dict(by_day)


def _gap_for(persona_cfg, day: int, hour: int) -> float:
    """Look up inter_msg_gap_min from the DayScript SessionPlan; default 5.0."""
    for ds in persona_cfg.days:
        if ds.day == day:
            for sp in ds.sessions:
                if sp.hour == hour:
                    return float(sp.inter_msg_gap_min)
    return 5.0


def synth_timestamps(day: int, session: dict, gap_min: float) -> list[datetime]:
    """Synthesise one timestamp per user message in a session."""
    base = datetime.combine(EPOCH + timedelta(days=day - 1), datetime.min.time())
    base = base.replace(hour=int(session["session_hour"]))
    n = len(session["exchanges"])
    return [base + timedelta(minutes=i * gap_min) for i in range(n)]


# ─────────────────────────────────────────────────────────────────────────────
# Stage 1 — temporal metrics (mirrors compute_temporal_metrics arithmetic)
# ─────────────────────────────────────────────────────────────────────────────

def stage1_temporal(rows: list[tuple[datetime, str]]) -> dict:
    """Compute Stage-1 metrics from (timestamp, user_message) rows for one day.

    Formulae copied verbatim from behavioral/temporal.py::compute_temporal_metrics.
    """
    if not rows:
        return {
            "daily_message_count": 0, "activity_by_hour": {}, "night_messages": 0,
            "daily_active_hours": 0, "avg_prompt_length_chars": 0,
            "avg_inter_message_interval_min": 0,
        }
    timestamps = [ts for ts, _ in rows]
    user_messages = [m for _, m in rows]

    activity_by_hour: dict[str, int] = {}
    for ts in timestamps:
        h = str(ts.hour)
        activity_by_hour[h] = activity_by_hour.get(h, 0) + 1

    night_messages = sum(1 for ts in timestamps if ts.hour in NIGHT_HOURS)
    avg_len = sum(len(m) for m in user_messages) / len(user_messages)

    if len(timestamps) >= 2:
        intervals = [
            (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
            for i in range(1, len(timestamps))
        ]
        avg_interval = sum(intervals) / len(intervals)
    else:
        avg_interval = 0.0

    return {
        "daily_message_count": len(timestamps),
        "activity_by_hour": activity_by_hour,
        "night_messages": night_messages,
        "daily_active_hours": len(activity_by_hour),
        "avg_prompt_length_chars": round(avg_len, 1),
        "avg_inter_message_interval_min": round(avg_interval, 2),
    }


# ─────────────────────────────────────────────────────────────────────────────
# Stage 2 — 5-class classification per session + aggregation
# ─────────────────────────────────────────────────────────────────────────────

def _conversation_text(session: dict) -> str:
    """Format a session's exchanges as a full user/assistant conversation."""
    parts = []
    for ex in session["exchanges"]:
        if ex.get("user"):
            parts.append(f"User: {ex['user']}")
        if ex.get("assistant"):
            parts.append(f"Assistant: {ex['assistant']}")
    return "\n".join(parts)


async def _classify_session(session: dict, cfg: "RunConfig") -> dict | None:
    """Run the 5-class classifier on one session. Returns the predict dict."""
    conversation = _conversation_text(session)
    kwargs: dict = dict(
        model=cfg.classifier_model,
        api_key=cfg.classifier_api_key,
        messages=[
            {"role": "system", "content": MULTI_LABEL_POLICY_PROMPT},
            {"role": "user", "content": conversation},
        ],
        temperature=cfg.temperature,
        response_format=SafetyMultilabelSchema,
        timeout=300,
    )
    if cfg.classifier_api_base:  # omit for openrouter/ routing
        kwargs["api_base"] = cfg.classifier_api_base
    attempts = 5
    for attempt in range(attempts):
        try:
            resp = await litellm.acompletion(**kwargs)
            content = resp.choices[0].message.content  # pyright: ignore[reportAttributeAccessIssue]
            parsed = SafetyMultilabelSchema.model_validate_json(content)
            return parsed.predict.model_dump()  # {suicide:{label,confidence}, ...}
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts - 1:
                print(f"  ! classifier failed ({exc.__class__.__name__}): {exc}")
                return None
            await asyncio.sleep(min(2 ** attempt, 30))
    return None


async def stage2_danger(day_sessions: list[dict], cfg: "RunConfig") -> tuple[dict, int, list[dict]]:
    """Classify every session of the day and aggregate.
    Returns (agg, n_failed, raw_predicts) — raw_predicts is the per-session
    predict dicts, kept for offline E8a replay recalibration."""
    preds = await asyncio.gather(*(_classify_session(s, cfg) for s in day_sessions))
    ok = [p for p in preds if p is not None]
    n_failed = len(preds) - len(ok)
    return _aggregate_predictions(ok), n_failed, ok


# ─────────────────────────────────────────────────────────────────────────────
# Stage 3 — behavioral LLM scoring (reuses the production prompt + parser)
# ─────────────────────────────────────────────────────────────────────────────

def build_stage3_sessions(day: int, day_sessions: list[dict], persona_cfg) -> list[dict]:
    """Build the session dicts Stage 3 expects: {start,end,messages,total}.

    `messages` are USER messages, sampled exactly as behavioral_llm._fetch_day_sessions:
    <=5 kept whole, >5 -> first 3 + last 2; then a global trim to ~30 messages.
    """
    sessions = []
    for s in day_sessions:
        gap = _gap_for(persona_cfg, day, int(s["session_hour"]))
        ts = synth_timestamps(day, s, gap)
        user_msgs = [ex["user"] for ex in s["exchanges"] if ex.get("user")]
        total = len(user_msgs)
        sampled = user_msgs if total <= 5 else user_msgs[:3] + user_msgs[-2:]
        sessions.append({
            "start": ts[0], "end": ts[-1] if ts else ts[0],
            "messages": sampled, "total": total,
        })
    sessions.sort(key=lambda x: x["start"])

    total_sampled = sum(len(s["messages"]) for s in sessions)
    if total_sampled > 30:
        for s in sorted(sessions, key=lambda x: x["total"], reverse=True):
            if total_sampled <= 30:
                break
            if len(s["messages"]) > 2:
                old = len(s["messages"])
                s["messages"] = [s["messages"][0], s["messages"][-1]]
                total_sampled -= old - 2
    return sessions


async def stage3_behavioral(today: date, sessions: list[dict], calendar: list,
                            cfg: "RunConfig") -> dict:
    """Run the Stage-3 LLM scorer. Returns {'scores': ..., 'summary': ...}."""
    prompt = _build_prompt(today, [], _format_calendar(calendar), sessions=sessions)
    kwargs: dict = dict(
        model=cfg.stage3_model,
        api_key=cfg.stage3_api_key,
        messages=[{"role": "user", "content": prompt}],
        temperature=cfg.temperature,
        timeout=300,
    )
    if cfg.stage3_api_base:  # omit for openrouter/ routing
        kwargs["api_base"] = cfg.stage3_api_base
    attempts = 5
    for attempt in range(attempts):
        # temp-0 retries are byte-identical, so an unparseable response can
        # never be escaped — perturb the temperature on retry to break the tie.
        if attempt > 0 and cfg.temperature == 0:
            kwargs["temperature"] = 0.4
        try:
            resp = await litellm.acompletion(**kwargs)
            content = resp.choices[0].message.content  # pyright: ignore[reportAttributeAccessIssue]
            parsed = _parse_llm_response(content)
            if parsed is not None:
                return parsed
        except Exception as exc:  # noqa: BLE001
            if attempt == attempts - 1:
                print(f"  ! stage3 failed ({exc.__class__.__name__}): {exc}")
        await asyncio.sleep(min(2 ** attempt, 30))
    print("  ! stage3 unparseable — using default zero scores for this day")
    return _default_result()


def _is_notable(summary: dict, scores: dict) -> bool:
    """Mirror behavioral/aggregator.py::_compute_is_notable."""
    if summary.get("life_events") or summary.get("ai_relationship_markers"):
        return True
    tone = (summary.get("emotional_tone") or "neutral").lower().strip()
    if tone not in ("neutral", "calm", "normal"):
        return True
    if scores.get("topic_concentration", 0) > 0.7:
        return True
    if scores.get("decision_delegation", 0) > 0.4:
        return True
    return False


# ─────────────────────────────────────────────────────────────────────────────
# Per-persona run
# ─────────────────────────────────────────────────────────────────────────────

def persona_class(persona_cfg) -> str:
    """Derive a coarse class from the expected_zone trajectory."""
    zones = [ds.expected_zone for ds in sorted(persona_cfg.days, key=lambda d: d.day)]
    if "RED" in zones:
        return "escalation"
    if "YELLOW" in zones:
        # recovery if it ends in GREEN after a YELLOW stretch
        if zones[-1] == "GREEN" and "YELLOW" in zones:
            return "recovery"
        return "sustained_yellow"
    return "control"


async def evaluate_persona(persona: str, cfg: "RunConfig") -> dict:
    """Run the full pipeline day-by-day for one persona. Returns a result dict."""
    persona_cfg = ALL_PERSONAS[persona]
    expected_by_day = {ds.day: ds.expected_zone for ds in persona_cfg.days}
    corpus = load_persona_corpus(cfg.corpus_dir, persona, cfg.generator)
    days = sorted(d for d in corpus if d in expected_by_day)
    if cfg.limit_days:
        days = days[: cfg.limit_days]

    history: list[SimpleNamespace] = []   # newest appended last
    calendar: list[SimpleNamespace] = []  # notable DailySummary stand-ins
    rows: list[dict] = []

    print(f"[{persona}] {len(days)} days, class={persona_class(persona_cfg)}")
    for day in days:
        day_sessions = corpus[day]
        today = EPOCH + timedelta(days=day - 1)

        # Stage 1
        ts_rows: list[tuple[datetime, str]] = []
        for s in day_sessions:
            gap = _gap_for(persona_cfg, day, int(s["session_hour"]))
            stamps = synth_timestamps(day, s, gap)
            for ts, ex in zip(stamps, s["exchanges"]):
                if ex.get("user"):
                    ts_rows.append((ts, ex["user"]))
        ts_rows.sort(key=lambda r: r[0])
        temporal = stage1_temporal(ts_rows)

        baselines = compute_baselines([h.temporal_metrics for h in history[-7:]])

        # Stage 2
        danger, n_failed, danger_raw = await stage2_danger(day_sessions, cfg)

        # Stage 3
        s3_sessions = build_stage3_sessions(day, day_sessions, persona_cfg)
        cal = calendar[-14:] if getattr(cfg, "use_calendar", True) else []
        stage3 = await stage3_behavioral(today, s3_sessions, cal, cfg)
        scores = stage3["scores"]
        summary = stage3["summary"]

        # Stage 4 — recent_history newest-first, as repo.get_recent_metrics returns
        recent = list(reversed(history))[:7]
        zone, triggers = await evaluate_risk_zone(
            temporal, danger, scores, baselines=baselines, recent_history=recent,
            context={"persona": persona, "date": today.isoformat(), "day": day},
        )

        expected = expected_by_day[day]
        rows.append({
            "persona": persona, "day": day, "phase": day_sessions[0].get("phase"),
            "expected_zone": expected, "predicted_zone": zone,
            "match": zone == expected, "triggered_rules": triggers,
            "n_sessions": len(day_sessions), "n_classifier_failed": n_failed,
            "temporal_metrics": temporal, "danger_class_agg": danger,
            "danger_predicts_raw": danger_raw,
            "behavioral_scores": scores,
        })

        history.append(SimpleNamespace(
            risk_zone=zone, danger_class_agg=danger,
            behavioral_scores=scores, temporal_metrics=temporal,
        ))
        if _is_notable(summary, scores):
            calendar.append(SimpleNamespace(
                summary_date=today,
                key_topics=summary.get("key_topics", []),
                life_events=summary.get("life_events", []),
                emotional_tone=summary.get("emotional_tone", "neutral"),
                ai_relationship_markers=summary.get("ai_relationship_markers", []),
                behavioral_scores=scores,
                risk_zone=zone,
            ))

        mark = "ok" if zone == expected else "MISS"
        print(f"  [{persona}] day {day:2d}: expected {expected:6s} -> {zone:6s} {mark}")

    predicted = [r["predicted_zone"] for r in rows]
    expected = [r["expected_zone"] for r in rows]
    first_red = next((rows[i]["day"] for i, z in enumerate(predicted) if z == "RED"), None)
    return {
        "persona": persona,
        "persona_class": persona_class(persona_cfg),
        "rows": rows,
        "trajectory_exact_match": predicted == expected,
        "day_of_first_red": first_red,
    }


# ─────────────────────────────────────────────────────────────────────────────
# Metrics
# ─────────────────────────────────────────────────────────────────────────────

def compute_metrics(results: list[dict]) -> dict:
    all_rows = [r for res in results for r in res["rows"]]
    n = len(all_rows)
    matched = sum(1 for r in all_rows if r["match"])

    zones = ("GREEN", "YELLOW", "RED")
    confusion = {e: {p: 0 for p in zones} for e in zones}
    for r in all_rows:
        confusion[r["expected_zone"]][r["predicted_zone"]] += 1

    # macro-F1 over the three zones (the DSPy target metric, reported for baseline)
    f1s = {}
    for z in zones:
        tp = confusion[z][z]
        fp = sum(confusion[e][z] for e in zones if e != z)
        fn = sum(confusion[z][p] for p in zones if p != z)
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        f1s[z] = 2 * prec * rec / (prec + rec) if prec + rec else 0.0

    green_expected = [r for r in all_rows if r["expected_zone"] == "GREEN"]
    false_alarms = sum(1 for r in green_expected if r["predicted_zone"] != "GREEN")

    return {
        "n_day_points": n,
        "n_personas": len(results),
        "zone_match_rate": round(matched / n, 4) if n else 0.0,
        "full_trajectory_match_rate": round(
            sum(1 for r in results if r["trajectory_exact_match"]) / len(results), 4
        ) if results else 0.0,
        "macro_f1": round(sum(f1s.values()) / 3, 4),
        "per_zone_f1": {z: round(v, 4) for z, v in f1s.items()},
        "fpr_on_green_personas": round(false_alarms / len(green_expected), 4)
        if green_expected else None,
        "confusion_expected_x_predicted": confusion,
        "day_of_first_red": {
            r["persona"]: r["day_of_first_red"] for r in results
        },
        "trajectory_exact_match": {
            r["persona"]: r["trajectory_exact_match"] for r in results
        },
    }


# ─────────────────────────────────────────────────────────────────────────────
# Config + main
# ─────────────────────────────────────────────────────────────────────────────

class RunConfig(SimpleNamespace):
    corpus_dir: Path
    generator: str
    classifier_model: str
    classifier_api_base: str
    classifier_api_key: str | None
    stage3_model: str
    stage3_api_base: str
    stage3_api_key: str | None
    temperature: float
    limit_days: int | None
    use_calendar: bool = True


def _git_sha(repo: Path) -> str:
    try:
        return subprocess.check_output(
            ["git", "-C", str(repo), "rev-parse", "HEAD"], text=True
        ).strip()
    except Exception:  # noqa: BLE001
        return "unknown"


async def _run(args) -> None:
    cfg = RunConfig(
        corpus_dir=Path(args.corpus_dir),
        generator=args.generator,
        classifier_model=args.classifier_model,
        classifier_api_base=args.classifier_api_base,
        classifier_api_key=args.classifier_api_key,
        stage3_model=args.stage3_model,
        stage3_api_base=args.stage3_api_base,
        stage3_api_key=args.stage3_api_key,
        temperature=args.temperature,
        limit_days=args.limit_days,
        use_calendar=args.use_calendar,
    )
    personas = args.personas or list(ALL_PERSONAS.keys())
    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    t_start = time.monotonic()
    sem = asyncio.Semaphore(args.concurrency)

    # Persist each persona's rows the moment that persona finishes, not at the
    # end. A killed or crashed run then keeps every persona completed so far
    # instead of losing the whole corpus.
    rows_path = out_dir / f"{stamp}_corpus_eval.jsonl"
    write_lock = asyncio.Lock()

    async def _guarded(p: str) -> dict | None:
        async with sem:
            try:
                res = await evaluate_persona(p, cfg)
            except FileNotFoundError as exc:
                print(f"[{p}] SKIPPED — {exc}")
                return None
            except Exception as exc:  # noqa: BLE001
                print(f"[{p}] FAILED — {exc.__class__.__name__}: {exc}")
                return None
        async with write_lock:
            with rows_path.open("a", encoding="utf-8") as fh:
                for r in res["rows"]:
                    fh.write(json.dumps(r, ensure_ascii=False) + "\n")
        return res

    raw = await asyncio.gather(*(_guarded(p) for p in personas), return_exceptions=True)
    results = [r for r in raw if isinstance(r, dict)]
    skipped = [p for p, r in zip(personas, raw) if not isinstance(r, dict)]
    if skipped:
        print(f"\n{len(skipped)} persona(s) skipped/failed: {', '.join(skipped)}")
    if not results:
        print("No personas evaluated successfully — aborting before write.")
        return
    wall = time.monotonic() - t_start

    # rows already written incrementally per-persona above; only the summary
    # remains to be written here.
    metrics = compute_metrics(results)
    summary = {
        "meta": {
            "experiment": "corpus_eval (chapter4 E2-E7 harness)",
            "run_at": datetime.now().isoformat(timespec="seconds"),
            "git_sha": _git_sha(SRC.parent.parent),
            "wall_seconds": round(wall, 1),
            "varied": {
                "personas_requested": personas,
                "personas_evaluated": [r["persona"] for r in results],
                "personas_skipped": skipped,
                "generator": cfg.generator,
            },
            "fixed": {
                "classifier_model": cfg.classifier_model,
                "classifier_api_base": cfg.classifier_api_base,
                "stage3_model": cfg.stage3_model,
                "stage3_api_base": cfg.stage3_api_base,
                "temperature": cfg.temperature,
                "temperature_note": "live pipeline uses 0.1; harness forces 0 for repeatability",
                "classifier_system_prompt": "prompts.MULTI_LABEL_POLICY_PROMPT",
                "stage3_prompt": "behavioral_llm._build_prompt (current repo version)",
                "response_format": "schemas.SafetyMultilabelSchema",
                "corpus_dir": str(cfg.corpus_dir),
                "concurrency": args.concurrency,
                "limit_days": cfg.limit_days,
            },
            "metrics": metrics,
        },
        "metrics": metrics,
        "rows_file": rows_path.name,
    }
    summary_path = out_dir / f"{stamp}_summary.json"
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")

    print(f"\nwrote {rows_path}")
    print(f"wrote {summary_path}")
    print(f"zone_match_rate={metrics['zone_match_rate']}  "
          f"macro_f1={metrics['macro_f1']}  "
          f"full_trajectory_match_rate={metrics['full_trajectory_match_rate']}  "
          f"fpr_on_green={metrics['fpr_on_green_personas']}")


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--personas", nargs="*", default=None,
                    help="persona keys (default: all 16)")
    ap.add_argument("--generator", default="deepseek",
                    help="corpus generator substring: deepseek | qwen36")
    ap.add_argument("--corpus-dir", default=str(DEFAULT_CORPUS))
    ap.add_argument("--no-calendar", dest="use_calendar", action="store_false",
                    help="E9 ablation: run Stage 3 with the longitudinal calendar disabled")
    ap.add_argument("--classifier-model", default="ollama_chat/gpt-oss-safeguard:latest")
    ap.add_argument("--classifier-api-base", default="http://192.168.87.25:11434")
    ap.add_argument("--classifier-api-key", default=os.environ.get("ROUTERAI_API_KEY"))
    ap.add_argument("--stage3-model", default="ollama_chat/qwen3:32b")
    ap.add_argument("--stage3-api-base", default="http://192.168.87.25:11434")
    ap.add_argument("--stage3-api-key", default=os.environ.get("ROUTERAI_API_KEY"))
    ap.add_argument("--temperature", type=float, default=0.0)
    ap.add_argument("--concurrency", type=int, default=3,
                    help="personas evaluated in parallel (days within a persona are sequential)")
    ap.add_argument("--limit-days", type=int, default=None,
                    help="evaluate only the first N days per persona (smoke test)")
    ap.add_argument("--out-dir", default=str(DEFAULT_OUT_DIR))
    args = ap.parse_args()
    asyncio.run(_run(args))


if __name__ == "__main__":
    main()
