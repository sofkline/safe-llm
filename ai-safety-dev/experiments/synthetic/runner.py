"""Main experiment runner: generate dialogues, insert into DB, run aggregator.

Usage:
    # Dry run: generate and preview (no DB, no LLM)
    py -m experiments.synthetic.runner --dry-run --persona viktor

    # Generate dialogues with LLM and insert into DB
    py -m experiments.synthetic.runner --persona viktor --plm-model openrouter/google/gemma-3-12b --clm-model openrouter/google/gemma-3-12b

    # Run aggregator only (data already in DB)
    py -m experiments.synthetic.runner --persona viktor --aggregate-only

    # Run all personas
    py -m experiments.synthetic.runner --all --plm-model openrouter/google/gemma-3-12b --clm-model openrouter/google/gemma-3-12b

    # Generate with Option B (deterministic PredictTable, no LLM classification)
    py -m experiments.synthetic.runner --persona viktor --option-b --plm-model openrouter/google/gemma-3-12b --clm-model openrouter/google/gemma-3-12b
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

# Ensure src is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from .personas import ALL_PERSONAS
from .personas.base import PersonaConfig
from .generator import generate_day
from .db_writer import build_spendlogs_rows, build_predict_row, insert_spendlogs_rows, insert_predict_row

logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("synthetic.runner")

DEFAULT_START_DATE = date(2026, 3, 10)


async def run_generation(
    persona: PersonaConfig,
    plm_model: str,
    clm_model: str,
    start_date: date = DEFAULT_START_DATE,
    dry_run: bool = False,
    option_b: bool = False,
) -> list[dict]:
    """Generate dialogues for all days and insert into DB.

    Returns list of per-day result dicts.
    """
    results = []
    total_rows = 0

    for ds in persona.days:
        logger.info("=== %s Day %d (%s) ===", persona.name, ds.day, ds.phase)

        if dry_run:
            # Preview mode: count expected messages without LLM calls
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

        # Generate dialogues via LLM
        day_results = await generate_day(persona, ds, plm_model, clm_model)

        # Build and insert SpendLogs rows
        all_rows = []
        for session_plan, exchanges in day_results:
            rows = build_spendlogs_rows(persona, ds, session_plan, exchanges, start_date)
            all_rows.extend(rows)

        inserted = await insert_spendlogs_rows(all_rows)
        total_rows += inserted
        logger.info("Day %d: inserted %d SpendLogs rows", ds.day, inserted)

        # Option B: insert deterministic PredictTable row
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


async def run_aggregation(
    persona: PersonaConfig,
    start_date: date = DEFAULT_START_DATE,
) -> list[dict]:
    """Run the behavioral aggregator day-by-day with time-travel mocking.

    Returns list of per-day result dicts with actual zones and triggers.
    """
    from behavioral.aggregator import run_aggregator_for_user
    from behavioral.repository import BehavioralRepository

    results = []

    for ds in persona.days:
        # Simulate running at 01:00 UTC the day after each data day
        simulated_now = datetime.combine(
            start_date + timedelta(days=ds.day),
            datetime.min.time().replace(hour=1),
            tzinfo=timezone.utc,
        )

        logger.info("Aggregating %s day %d (simulated time: %s)", persona.name, ds.day, simulated_now)

        # Mock datetime.now() in all pipeline modules
        modules_to_mock = [
            "behavioral.temporal",
            "behavioral.danger_agg",
            "behavioral.behavioral_llm",
            "behavioral.aggregator",
        ]
        patches = []
        for mod in modules_to_mock:
            p = patch(f"{mod}.datetime")
            mock_dt = p.start()
            mock_dt.now.return_value = simulated_now
            mock_dt.combine = datetime.combine
            mock_dt.min = datetime.min
            mock_dt.side_effect = lambda *a, **k: datetime(*a, **k)
            patches.append(p)

        try:
            await run_aggregator_for_user(persona.persona_id)
        except Exception as e:
            logger.error("Aggregation failed for day %d: %s", ds.day, e)
        finally:
            for p in patches:
                p.stop()

        # Collect results
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

    # Summary
    total = len(results)
    correct = sum(1 for r in results if r["match"])
    logger.info("Aggregation complete: %s, %d/%d correct (%.0f%%)",
                persona.name, correct, total, correct / total * 100 if total else 0)

    return results


def export_results(results: list[dict], output_path: Path):
    """Export results to CSV."""
    if not results:
        return
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with output_path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=results[0].keys())
        writer.writeheader()
        writer.writerows(results)
    logger.info("Results saved to %s", output_path)


async def main():
    parser = argparse.ArgumentParser(description="Synthetic dialogue experiment runner")
    parser.add_argument("--persona", type=str, help="Persona name (e.g. 'viktor')")
    parser.add_argument("--all", action="store_true", help="Run all personas")
    parser.add_argument("--plm-model", type=str, default="openrouter/google/gemma-3-12b",
                        help="Model for Patient LM")
    parser.add_argument("--clm-model", type=str, default="openrouter/google/gemma-3-12b",
                        help="Model for Clinician LM")
    parser.add_argument("--start-date", type=str, default="2026-03-10",
                        help="Start date (YYYY-MM-DD)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without LLM calls or DB insertion")
    parser.add_argument("--option-b", action="store_true",
                        help="Use deterministic PredictTable values (Option B)")
    parser.add_argument("--aggregate-only", action="store_true",
                        help="Skip generation, only run aggregator")
    parser.add_argument("--output", type=str, default=None,
                        help="Output CSV path for results")
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

        if args.aggregate_only:
            results = await run_aggregation(persona, start_date)
        else:
            gen_results = await run_generation(
                persona, args.plm_model, args.clm_model,
                start_date, args.dry_run, args.option_b,
            )
            if not args.dry_run:
                results = await run_aggregation(persona, start_date)
            else:
                results = gen_results

        all_results.extend(results)

    # Export
    if args.output and all_results:
        export_results(all_results, Path(args.output))

    # Print summary
    if not args.dry_run and not args.aggregate_only:
        print(f"\n{'='*60}")
        print("SUMMARY")
        print(f"{'='*60}")
        for r in all_results:
            if "actual_zone" in r:
                mark = "ok" if r["match"] else "MISS"
                print(f"  {r['persona']:10s} day {r['day']:2d}: "
                      f"expected={r['expected_zone']:6s} actual={r['actual_zone']:6s} [{mark}]")


if __name__ == "__main__":
    asyncio.run(main())
