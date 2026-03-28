# Планировщик скрапера Langfuse: Prod каждый час, Dev каждые 5 секунд
from datetime import timezone, datetime, UTC, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from langfuse_scraper import scrape_sessions_for_previous_hour, logger


async def start_langfuse_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    if settings.is_develop_mode:
        trigger = CronTrigger(second=5)
    else:
        trigger = IntervalTrigger(
            hours=settings.SCRAPE_HOURS_WINDOW,
            start_date=datetime.now(UTC) + timedelta(minutes=1),
        )

    scheduler.add_job(
        scrape_sessions_for_previous_hour,
        trigger,
        id="langfuse_sessions_hourly",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    scheduler.start()
    logger.info("Langfuse sessions scheduler started (hourly, UTC).")
    return scheduler
