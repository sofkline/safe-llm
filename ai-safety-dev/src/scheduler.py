from datetime import timezone, datetime, UTC, timedelta

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from config import settings
from database.repository import PredictRepository
from langfuse_scraper import scrape_sessions_for_previous_hour, logger


async def start_langfuse_scheduler() -> AsyncIOScheduler:
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    predict_repository = PredictRepository()
    last_time_recorded = await predict_repository.last_time_recorded_by_all_users()
    for record in last_time_recorded:
        if settings.is_develop_mode:
            trigger = CronTrigger(second=5)
        else:
            start_date = max(record.created_at + settings.SCRAPE_HOURS_WINDOW, datetime.now(UTC) + timedelta(minutes=1))
            trigger = IntervalTrigger(hours=settings.SCRAPE_HOURS_WINDOW, start_date=start_date)

        scheduler.add_job(
            scrape_sessions_for_previous_hour,
            trigger,
            id=f"langfuse_sessions_hourly_{record.user_id}",
            replace_existing=True,
            max_instances=1,
            coalesce=True,
            misfire_grace_time=300,
        )
    scheduler.start()
    logger.info("Langfuse sessions scheduler started (hourly, UTC).")
    return scheduler
