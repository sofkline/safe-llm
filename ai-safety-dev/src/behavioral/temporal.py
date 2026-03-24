"""Stage 1: Temporal metrics from SpendLogs. Implemented in Milestone 2."""

import logging

logger = logging.getLogger(__name__)


async def compute_temporal_metrics(end_user_id: str) -> dict:
    """Compute 24h temporal metrics for a user. Returns temporal_metrics JSON.

    Stub: returns empty metrics. Full implementation in Milestone 2.
    """
    logger.info("Stage 1 (temporal): stub for user %s", end_user_id)
    return {
        "daily_message_count": 0,
        "activity_by_hour": {},
        "night_messages": 0,
        "daily_active_hours": 0,
        "avg_prompt_length_chars": 0,
        "avg_inter_message_interval_min": 0,
        "messages_last_1h": 0,
    }
