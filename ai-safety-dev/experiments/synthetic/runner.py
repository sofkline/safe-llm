"""Iterative experiment runner: clean -> archive -> generate -> classify -> aggregate.

Every non-dry-run automatically cleans previous data and archives it to CSV.
No data mixing between iterations.

Usage:
    # Preview (no LLM, no DB)
    PYTHONPATH=experiments py -m synthetic.runner --dry-run --persona viktor

    # Iteration 1: full pipeline (auto-cleans DB, archives nothing since DB is empty)
    PYTHONPATH=experiments py -m synthetic.runner --persona sara \
      --classify \
      --plm-model openrouter/google/gemma-3-12b \
      --clm-model openrouter/google/gemma-3-12b

    # Fix pipeline code, re-run iteration 2 (archives iteration 1 to CSV, cleans DB)
    PYTHONPATH=experiments py -m synthetic.runner --persona sara \
      --classify \
      --plm-model openrouter/google/gemma-3-12b \
      --clm-model openrouter/google/gemma-3-12b

    # Re-aggregate only (keeps SpendLogs+PredictTable, re-runs Stages 1-4)
    PYTHONPATH=experiments py -m synthetic.runner --persona sara --reaggregate

    # Final run for all personas
    PYTHONPATH=experiments py -m synthetic.runner --all --classify \
      --plm-model openrouter/google/gemma-3-12b \
      --clm-model openrouter/google/gemma-3-12b
"""

import argparse
import asyncio
import csv
import json
import logging
import sys
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from .personas import ALL_PERSONAS
from .personas.base import PersonaConfig
from .generator import generate_day
from .db_writer import build_spendlogs_rows, build_predict_row, insert_spendlogs_rows, insert_predict_row

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("synthetic.runner")

DEFAULT_START_DATE = date(2026, 3, 10)
RESULTS_DIR = Path(__file__).resolve().parent.parent / "results"


# == Archive + Clean ======================================================

def _next_iteration_number(persona_name: str) -> int:
    """Find next iteration number by checking existing archive folders."""
    persona_dir = RESULTS_DIR / persona_name.lower()
    if not persona_dir.exists():
        return 1
    existing = [
        d.name for d in persona_dir.iterdir()
        if d.is_dir() and d.name.startswith("iteration_")
    ]
    if not existing:
        return 1
    nums = []
    for name in existing:
        try:
            nums.append(int(name.split("_")[1]))
        except (IndexError, ValueError):
            pass
    return max(nums) + 1 if nums else 1


def _write_csv(rows: list[dict], path: Path):
    """Write list of dicts to CSV."""
    if not rows:
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=rows[0].keys())
        writer.writeheader()
        writer.writerows(rows)


async def archive_persona_data(persona: PersonaConfig) -> Path | None:
    """Export current DB data for persona to CSV archive. Returns archive dir or None."""
    from database import Session
    from database.models import LiteLLM_SpendLogs, LiteLLM_PredictTable
    from behavioral.models import (
        UserBehaviorProfile, MetricsHistory, DailySummary, BehavioralEvent,
    )
    from sqlalchemy import select

    pid = persona.persona_id

    async with Session() as session:
        # Check if there's any data to archive
        result = await session.execute(
            select(LiteLLM_SpendLogs).where(LiteLLM_SpendLogs.end_user == pid).limit(1)
        )
        if not result.scalars().first():
            logger.info("No existing data for %s, nothing to archive", pid)
            return None

        # SpendLogs
        result = await session.execute(
            select(LiteLLM_SpendLogs)
            .where(LiteLLM_SpendLogs.end_user == pid)
            .order_by(LiteLLM_SpendLogs.startTime.asc())
        )
        spendlogs = [
            {
                "request_id": r.request_id,
                "startTime": str(r.startTime),
                "end_user": r.end_user,
                "session_id": r.session_id,
                "model": r.model,
                "messages_preview": str(r.messages)[:200] if r.messages else "",
                "metadata": json.dumps(r.metadata_json) if r.metadata_json else "",
            }
            for r in result.scalars().all()
        ]

        # PredictTable
        result = await session.execute(
            select(LiteLLM_PredictTable).where(LiteLLM_PredictTable.user_id == pid)
        )
        predicts = [
            {
                "session_id": r.session_id,
                "user_id": r.user_id,
                "predict": json.dumps(r.predict) if r.predict else "",
            }
            for r in result.scalars().all()
        ]

        # MetricsHistory
        result = await session.execute(
            select(MetricsHistory)
            .where(MetricsHistory.end_user_id == pid)
            .order_by(MetricsHistory.computed_at.asc())
        )
        metrics = [
            {
                "computed_at": str(r.computed_at),
                "risk_zone": r.risk_zone,
                "temporal_metrics": json.dumps(r.temporal_metrics) if r.temporal_metrics else "",
                "danger_class_agg": json.dumps(r.danger_class_agg) if r.danger_class_agg else "",
                "behavioral_scores": json.dumps(r.behavioral_scores) if r.behavioral_scores else "",
            }
            for r in result.scalars().all()
        ]

        # DailySummary
        result = await session.execute(
            select(DailySummary)
            .where(DailySummary.end_user_id == pid)
            .order_by(DailySummary.summary_date.asc())
        )
        summaries = [
            {
                "summary_date": str(r.summary_date),
                "key_topics": json.dumps(r.key_topics) if r.key_topics else "",
                "life_events": json.dumps(r.life_events) if r.life_events else "",
                "emotional_tone": r.emotional_tone,
                "ai_relationship_markers": json.dumps(r.ai_relationship_markers) if r.ai_relationship_markers else "",
                "notable_quotes": json.dumps(r.notable_quotes) if r.notable_quotes else "",
                "operator_note": r.operator_note,
                "is_notable": r.is_notable,
            }
            for r in result.scalars().all()
        ]

        # BehavioralEvents
        result = await session.execute(
            select(BehavioralEvent)
            .where(BehavioralEvent.end_user_id == pid)
            .order_by(BehavioralEvent.detected_at.asc())
        )
        events = [
            {
                "detected_at": str(r.detected_at),
                "event_type": r.event_type,
                "details": json.dumps(r.details) if r.details else "",
            }
            for r in result.scalars().all()
        ]

    # Determine iteration number
    iteration_num = _next_iteration_number(persona.name)
    archive_dir = RESULTS_DIR / persona.name.lower() / f"iteration_{iteration_num}"
    archive_dir.mkdir(parents=True, exist_ok=True)

    _write_csv(spendlogs, archive_dir / "spendlogs.csv")
    _write_csv(predicts, archive_dir / "predict.csv")
    _write_csv(metrics, archive_dir / "behavioral.csv")
    _write_csv(summaries, archive_dir / "daily_summaries.csv")
    _write_csv(events, archive_dir / "events.csv")

    # Write summary
    with (archive_dir / "summary.txt").open("w", encoding="utf-8") as f:
        f.write(f"Persona: {persona.name} ({persona.name_ru})\n")
        f.write(f"Iteration: {iteration_num}\n")
        f.write(f"Archived at: {datetime.now().isoformat()}\n")
        f.write(f"SpendLogs rows: {len(spendlogs)}\n")
        f.write(f"PredictTable rows: {len(predicts)}\n")
        f.write(f"MetricsHistory rows: {len(metrics)}\n")
        f.write(f"DailySummary rows: {len(summaries)}\n")
        f.write(f"BehavioralEvent rows: {len(events)}\n")

    logger.info("Archived %s iteration %d to %s", persona.name, iteration_num, archive_dir)
    return archive_dir


async def clean_persona_data(persona: PersonaConfig, keep_spendlogs: bool = False):
    """Delete all experiment data for a persona from DB.

    If keep_spendlogs=True, only deletes behavioral + predict tables
    (for --reaggregate where we keep generated dialogues).
    """
    from database import Session
    from database.models import LiteLLM_SpendLogs, LiteLLM_PredictTable
    from behavioral.models import (
        UserBehaviorProfile, MetricsHistory, DailySummary, BehavioralEvent,
    )
    from sqlalchemy import delete

    pid = persona.persona_id

    async with Session() as session:
        async with session.begin():
            # Always clean behavioral tables
            await session.execute(
                delete(BehavioralEvent).where(BehavioralEvent.end_user_id == pid))
            await session.execute(
                delete(DailySummary).where(DailySummary.end_user_id == pid))
            await session.execute(
                delete(MetricsHistory).where(MetricsHistory.end_user_id == pid))
            await session.execute(
                delete(UserBehaviorProfile).where(UserBehaviorProfile.end_user_id == pid))

            if not keep_spendlogs:
                await session.execute(
                    delete(LiteLLM_PredictTable).where(LiteLLM_PredictTable.user_id == pid))
                await session.execute(
                    delete(LiteLLM_SpendLogs).where(LiteLLM_SpendLogs.end_user == pid))

    what = "behavioral data" if keep_spendlogs else "ALL data"
    logger.info("Cleaned %s for %s", what, pid)


# == Classify ==============================================================

async def _ensure_user_exists(persona: PersonaConfig):
    """Create a LiteLLM_UserTable row for the synthetic user if it doesn't exist."""
    from database import Session as DBSession
    from database.models import LiteLLM_UserTable

    pid = persona.persona_id
    async with DBSession() as session:
        async with session.begin():
            existing = await session.get(LiteLLM_UserTable, pid)
            if not existing:
                user = LiteLLM_UserTable(user_id=pid)
                session.add(user)
                logger.info("Created LiteLLM_UserTable row for %s", pid)


async def classify_persona_spendlogs(persona: PersonaConfig):
    """Run 5-class LLM classification on SpendLogs -> PredictTable."""
    from database import Session as DBSession
    from database.models import LiteLLM_SpendLogs, LiteLLM_PredictTable
    from database.repository import PredictRepository
    from classificators import daily_classification
    from sqlalchemy import select

    pid = persona.persona_id
    predict_repo = PredictRepository()

    # PredictTable has FK to LiteLLM_UserTable — ensure user exists
    await _ensure_user_exists(persona)

    async with DBSession() as session:
        query = (
            select(LiteLLM_SpendLogs)
            .where(LiteLLM_SpendLogs.end_user == pid)
            .order_by(LiteLLM_SpendLogs.startTime.asc())
        )
        result = await session.execute(query)
        rows = result.scalars().all()

    if not rows:
        logger.warning("No SpendLogs for %s, nothing to classify", pid)
        return

    # Group by session_id, take last row per session (cumulative messages)
    sessions: dict[str, object] = {}
    for row in rows:
        sid = row.session_id or row.request_id
        sessions[sid] = row

    logger.info("Classifying %d sessions for %s", len(sessions), pid)
    classified = 0

    for session_id, row in sessions.items():
        messages = row.messages if isinstance(row.messages, list) else []
        if not messages:
            continue

        conversation = "\n\n".join(
            f"{msg['role']}: {msg['content']}"
            for msg in messages
            if isinstance(msg, dict) and "role" in msg and "content" in msg
        )

        try:
            result = await daily_classification(conversation=conversation)
            predict = LiteLLM_PredictTable(
                last_trace_id=row.request_id,
                session_id=session_id,
                user_id=pid,
                predict={"predict": result.model_dump()},
            )
            await predict_repo.add(predict)
            classified += 1
        except Exception as e:
            logger.error("Classification failed for session %s: %s", session_id, e)

    logger.info("Classified %d/%d sessions for %s", classified, len(sessions), pid)


# == Generate ==============================================================

async def run_generation(
    persona: PersonaConfig,
    plm_model: str,
    clm_model: str,
    start_date: date = DEFAULT_START_DATE,
    dry_run: bool = False,
    option_b: bool = False,
    api_base: str | None = None,
) -> list[dict]:
    """Generate dialogues for all days and insert into DB."""
    results = []
    total_rows = 0

    for ds in persona.days:
        logger.info("=== %s Day %d (%s) ===", persona.name, ds.day, ds.phase)

        if dry_run:
            expected_msgs = sum(s.max_turns for s in ds.sessions)
            print(f"  Day {ds.day:2d} [{ds.phase:6s}] "
                  f"sessions={len(ds.sessions)} turns={expected_msgs} "
                  f"topic='{ds.primary_topic}' tone='{ds.emotional_tone}'")
            if ds.life_event:
                print(f"         event: {ds.life_event}")
            if ds.ai_markers:
                print(f"         markers: {', '.join(ds.ai_markers)}")
            results.append({
                "day": ds.day, "phase": ds.phase,
                "expected_zone": ds.expected_zone,
                "sessions": len(ds.sessions),
                "expected_turns": expected_msgs,
            })
            continue

        day_results = await generate_day(persona, ds, plm_model, clm_model, api_base)

        all_rows = []
        for session_plan, exchanges in day_results:
            rows = build_spendlogs_rows(persona, ds, session_plan, exchanges, start_date)
            all_rows.extend(rows)

        inserted = await insert_spendlogs_rows(all_rows)
        total_rows += inserted
        logger.info("Day %d: inserted %d SpendLogs rows", ds.day, inserted)

        if option_b:
            session_id = f"synth_{persona.persona_id}_d{ds.day}"
            predict_data = build_predict_row(persona, ds, session_id)
            if predict_data:
                await insert_predict_row(predict_data)
                logger.info("Day %d: inserted PredictTable row (Option B)", ds.day)

        results.append({
            "day": ds.day, "phase": ds.phase,
            "expected_zone": ds.expected_zone,
            "spendlogs_rows": inserted,
        })

    logger.info("Generation complete: %s, %d days, %d total SpendLogs rows",
                persona.name, len(persona.days), total_rows)
    return results


# == Aggregate =============================================================

async def run_aggregation(
    persona: PersonaConfig,
    start_date: date = DEFAULT_START_DATE,
) -> list[dict]:
    """Run the behavioral aggregator day-by-day with time-travel mocking."""
    from behavioral.aggregator import run_aggregator_for_user
    from behavioral.repository import BehavioralRepository

    results = []

    for ds in persona.days:
        simulated_now = datetime.combine(
            start_date + timedelta(days=ds.day),
            datetime.min.time().replace(hour=1),
            tzinfo=timezone.utc,
        )

        logger.info("Aggregating %s day %d (simulated time: %s)",
                     persona.name, ds.day, simulated_now)

        # Mock datetime in all pipeline modules so they see simulated_now
        # Need naive version for modules using datetime.utcnow()
        simulated_naive = simulated_now.replace(tzinfo=None)

        modules_to_mock = [
            "behavioral.temporal",
            "behavioral.danger_agg",
            "behavioral.behavioral_llm",
            "behavioral.aggregator",
            "behavioral.repository",
        ]
        patches = []
        for mod in modules_to_mock:
            p = patch(f"{mod}.datetime", wraps=datetime)
            mock_dt = p.start()
            mock_dt.now.return_value = simulated_now
            mock_dt.utcnow.return_value = simulated_naive
            patches.append(p)

        try:
            await run_aggregator_for_user(persona.persona_id)
        except Exception as e:
            logger.error("Aggregation failed for day %d: %s", ds.day, e)
        finally:
            for p in patches:
                p.stop()

        repo = BehavioralRepository()
        profile = await repo.get_profile(persona.persona_id)
        actual_zone = profile.risk_zone if profile else "NO_DATA"

        match = actual_zone == ds.expected_zone
        status = "ok" if match else "MISMATCH"

        results.append({
            "persona": persona.name,
            "day": ds.day,
            "date": str(start_date + timedelta(days=ds.day - 1)),
            "phase": ds.phase,
            "expected_zone": ds.expected_zone,
            "actual_zone": actual_zone,
            "match": match,
        })

        logger.info("Day %d: expected=%s actual=%s [%s]",
                     ds.day, ds.expected_zone, actual_zone, status)

    total = len(results)
    correct = sum(1 for r in results if r["match"])
    logger.info("Aggregation complete: %s, %d/%d correct (%.0f%%)",
                persona.name, correct, total, correct / total * 100 if total else 0)

    return results


# == Summary ===============================================================

def print_summary(all_results: list[dict]):
    """Print human-readable summary."""
    agg_results = [r for r in all_results if "actual_zone" in r]
    if not agg_results:
        return

    print(f"\n{'='*60}")
    print("RESULTS")
    print(f"{'='*60}")

    for r in agg_results:
        mark = "ok" if r["match"] else "MISS"
        print(f"  {r['persona']:10s} day {r['day']:2d}: "
              f"expected={r['expected_zone']:6s} actual={r['actual_zone']:6s} [{mark}]")

    total = len(agg_results)
    correct = sum(1 for r in agg_results if r["match"])
    pct = correct / total * 100 if total else 0
    print(f"\n  Score: {correct}/{total} ({pct:.0f}%)")

    misses = [r for r in agg_results if not r["match"]]
    if misses:
        print(f"\n  Mismatches to investigate:")
        for r in misses:
            print(f"    {r['persona']} day {r['day']}: "
                  f"expected {r['expected_zone']}, got {r['actual_zone']}")
    else:
        print("  All zones match expected trajectory!")


# == Main ==================================================================

async def main():
    parser = argparse.ArgumentParser(
        description="Iterative synthetic experiment runner",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Workflow:
  Iteration 1:  generate -> classify -> aggregate -> review results
  Fix code...
  Iteration 2:  (auto-archives iteration 1) -> generate -> classify -> aggregate
  Fix code...
  Iteration 3:  --reaggregate (keeps dialogues, re-runs pipeline only)

Data safety: every run auto-archives previous data to
  experiments/results/{persona}/iteration_{N}/
  then cleans DB before inserting new data. No mixing.
""",
    )
    parser.add_argument("--persona", type=str, help="Persona name (e.g. 'viktor')")
    parser.add_argument("--all", action="store_true", help="Run all personas")
    parser.add_argument("--plm-model", type=str, default="openrouter/google/gemma-3-12b",
                        help="Model for Patient LM")
    parser.add_argument("--clm-model", type=str, default="openrouter/google/gemma-3-12b",
                        help="Model for Clinician LM")
    parser.add_argument("--api-base", type=str, default=None,
                        help="API base URL for Ollama/local models (e.g. http://192.168.87.25:11434)")
    parser.add_argument("--start-date", type=str, default="2026-03-10",
                        help="Start date (YYYY-MM-DD)")

    # Pipeline mode
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without LLM calls or DB insertion")
    parser.add_argument("--classify", action="store_true",
                        help="Run 5-class LLM classification after generation")
    parser.add_argument("--option-b", action="store_true",
                        help="Use deterministic PredictTable values instead of --classify")
    parser.add_argument("--reaggregate", action="store_true",
                        help="Keep SpendLogs+PredictTable, only re-run behavioral pipeline")

    args = parser.parse_args()
    start_date = date.fromisoformat(args.start_date)

    # Select personas
    if args.all:
        personas = list(ALL_PERSONAS.values())
    elif args.persona:
        key = args.persona.lower()
        if key not in ALL_PERSONAS:
            print(f"Unknown persona '{key}'. Available: {', '.join(ALL_PERSONAS.keys())}")
            return
        personas = [ALL_PERSONAS[key]]
    else:
        print("Specify --persona <name> or --all")
        print(f"Available: {', '.join(ALL_PERSONAS.keys())}")
        return

    all_results = []

    for persona in personas:
        print(f"\n{'='*60}")
        print(f"Persona: {persona.name} ({persona.name_ru}), {persona.age}")
        print(f"Trajectory: {persona.trajectory}")
        print(f"Tests: {persona.tests_what}")
        print(f"Days: {persona.total_days}")
        print(f"{'='*60}")

        if args.dry_run:
            gen_results = await run_generation(
                persona, args.plm_model, args.clm_model,
                start_date, dry_run=True, api_base=args.api_base,
            )
            all_results.extend(gen_results)
            continue

        # Step 0: Archive previous data + clean DB
        if args.reaggregate:
            # Keep SpendLogs + PredictTable, only clean behavioral
            await archive_persona_data(persona)
            await clean_persona_data(persona, keep_spendlogs=True)
        else:
            # Full clean: archive everything, delete everything
            await archive_persona_data(persona)
            await clean_persona_data(persona, keep_spendlogs=False)

        # Step 1: Generate dialogues (skip if reaggregate)
        if not args.reaggregate:
            await run_generation(
                persona, args.plm_model, args.clm_model,
                start_date, dry_run=False, option_b=args.option_b,
                api_base=args.api_base,
            )

        # Step 2: Classify SpendLogs -> PredictTable (skip if reaggregate or option_b)
        if args.classify and not args.reaggregate:
            await classify_persona_spendlogs(persona)

        # Step 3: Run aggregator
        results = await run_aggregation(persona, start_date)
        all_results.extend(results)

        # Step 4: Auto-export this iteration's aggregation results
        iteration_num = _next_iteration_number(persona.name) - 1  # just archived
        if iteration_num < 1:
            iteration_num = 1
        result_dir = RESULTS_DIR / persona.name.lower() / f"iteration_{iteration_num}"
        result_dir.mkdir(parents=True, exist_ok=True)
        _write_csv(results, result_dir / "aggregation.csv")

    # Print summary
    print_summary(all_results)


if __name__ == "__main__":
    asyncio.run(main())
