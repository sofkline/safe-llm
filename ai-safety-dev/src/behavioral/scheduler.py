"""Daily APScheduler job for behavioral aggregation."""

import logging
from datetime import timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import select, distinct

from config import settings
from database import Session
from database.models import LiteLLM_SpendLogs
from behavioral.aggregator import run_aggregator_for_user

logger = logging.getLogger(__name__)


async def _get_active_user_ids() -> list[str]:
    """Fetch distinct end_user IDs from SpendLogs."""
    async with Session() as session:
        query = select(distinct(LiteLLM_SpendLogs.end_user)).where(
            LiteLLM_SpendLogs.end_user.is_not(None)
        )
        result = await session.execute(query)
        return [row[0] for row in result.all()]


async def _run_daily_aggregation():
    """Run aggregator for all active users."""
    user_ids = await _get_active_user_ids()
    logger.info("Daily behavioral aggregation: processing %d users", len(user_ids))
    for user_id in user_ids:
        try:
            await run_aggregator_for_user(user_id)
        except Exception:
            logger.exception("Aggregator failed for user %s", user_id)


async def start_behavioral_scheduler() -> AsyncIOScheduler:
    """Start the daily behavioral aggregation scheduler."""
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    if settings.is_develop_mode:
        trigger = IntervalTrigger(seconds=30)
        logger.info("Behavioral scheduler: dev mode, running every 30s")
    else:
        trigger = CronTrigger(hour=0, minute=30)
        logger.info("Behavioral scheduler: production, running daily at 00:30 UTC")

    scheduler.add_job(
        _run_daily_aggregation,
        trigger,
        id="behavioral_daily_aggregation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    return scheduler
