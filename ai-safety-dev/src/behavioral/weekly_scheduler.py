# behavioral/scheduler.py

import logging
from datetime import datetime, timedelta, timezone, UTC
from pathlib import Path

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import select, distinct, and_

from config import settings
from database import Session
from database.models import LiteLLM_SpendLogs
from behavioral.weekly_report import generate_weekly_report

logger = logging.getLogger(__name__)

WEEKLY_REPORTS_DIR = Path("weekly_reports")


async def _get_active_user_ids() -> list[str]:
    """Exact same logic as now: active in last 48h."""
    cutoff = datetime.utcnow() - timedelta(hours=48)
    async with Session() as session:
        query = select(distinct(LiteLLM_SpendLogs.end_user)).where(
            and_(
                LiteLLM_SpendLogs.end_user.is_not(None),
                LiteLLM_SpendLogs.startTime >= cutoff,
            )
        )
        result = await session.execute(query)
        return [row[0] for row in result.all()]


async def _run_weekly_reports_for_all_users():
    """Generate weekly reports and save to repo folder."""
    user_ids = await _get_active_user_ids()
    user_ids = [uid for uid in user_ids if uid and uid.strip()]
    WEEKLY_REPORTS_DIR.mkdir(parents=True, exist_ok=True)

    week_end = datetime.now(UTC).date()
    logger.info(
        "Weekly reports: generating for %d users (week ending %s)",
        len(user_ids),
        week_end,
    )

    for user_id in user_ids:
        try:
            report_text = await generate_weekly_report(
                end_user_id=user_id,
                report_date=week_end,
            )
            filename = WEEKLY_REPORTS_DIR / f"{user_id}_{week_end.isoformat()}.txt"
            filename.write_text(report_text, encoding="utf-8")
        except Exception:
            logger.exception("Weekly report failed for user %s", user_id)


async def start_weekly_scheduler() -> AsyncIOScheduler:
    """Existing daily + new weekly reporting layer."""
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    # WEEKLY REPORTING LAYER
    if settings.is_develop_mode:
        # для теста — каждые N минут
        weekly_trigger = IntervalTrigger(minutes=7)
        logger.info("Weekly reports: dev mode, running every 7 minutes")
    else:
        # раз в неделю, например, в понедельник 02:00 UTC
        weekly_trigger = CronTrigger(day_of_week="mon", hour=2, minute=0)
        logger.info(
            "Weekly reports: production, running weekly on Monday at 02:00 UTC"
        )

    scheduler.add_job(
        _run_weekly_reports_for_all_users,
        weekly_trigger,
        id="behavioral_weekly_reports",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    return scheduler