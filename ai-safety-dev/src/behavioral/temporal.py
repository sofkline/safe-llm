"""Stage 1: Temporal metrics from SpendLogs."""

import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, and_

from database import Session
from database.models import LiteLLM_SpendLogs

logger = logging.getLogger(__name__)

NIGHT_HOURS = {22, 23, 0, 1, 2, 3}


def _extract_last_user_message(messages) -> str | None:
    """Extract the last user message from a cumulative messages array.

    SpendLogs stores the full conversation history per row.
    The current user message is the last element with role='user'.
    """
    if not messages or not isinstance(messages, list):
        return None
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content")
    return None


async def _fetch_spendlogs_rows(
    end_user_id: str, since: datetime
) -> list[tuple[datetime, list]]:
    """Fetch (startTime, messages) pairs from SpendLogs for a user since a cutoff."""
    async with Session() as session:
        query = (
            select(
                LiteLLM_SpendLogs.startTime,
                LiteLLM_SpendLogs.messages,
            )
            .where(
                and_(
                    LiteLLM_SpendLogs.end_user == end_user_id,
                    LiteLLM_SpendLogs.startTime >= since,
                )
            )
            .order_by(LiteLLM_SpendLogs.startTime.asc())
        )
        result = await session.execute(query)
        return [(row[0], row[1]) for row in result.all()]


async def compute_temporal_metrics(end_user_id: str) -> dict:
    """Compute 24h temporal metrics for a user from SpendLogs.

    Returns a dict with all Stage 1 metric fields.
    """
    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)

    rows = await _fetch_spendlogs_rows(end_user_id, since_24h)

    if not rows:
        return _empty_metrics()

    # Extract user messages and timestamps
    timestamps: list[datetime] = []
    user_messages: list[str] = []
    for start_time, messages_json in rows:
        msg = _extract_last_user_message(messages_json)
        if msg is not None:
            timestamps.append(start_time)
            user_messages.append(msg)

    if not timestamps:
        return _empty_metrics()

    # 1. daily_message_count
    daily_message_count = len(timestamps)

    # 2. activity_by_hour — histogram {"0": N, ..., "23": N}
    # String keys for JSON round-trip compatibility (PostgreSQL JSON returns string keys)
    activity_by_hour = {}
    for ts in timestamps:
        h = str(ts.hour)
        activity_by_hour[h] = activity_by_hour.get(h, 0) + 1

    # 3. night_messages — hours 22, 23, 0, 1, 2, 3
    night_messages = sum(1 for ts in timestamps if ts.hour in NIGHT_HOURS)

    # 4. daily_active_hours — distinct hours with >=1 message
    daily_active_hours = len(activity_by_hour)

    # 5. avg_prompt_length_chars
    avg_prompt_length_chars = (
        sum(len(m) for m in user_messages) / len(user_messages)
        if user_messages
        else 0
    )

    # 6. avg_inter_message_interval_min
    if len(timestamps) >= 2:
        intervals = []
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
            intervals.append(gap)
        avg_inter_message_interval_min = sum(intervals) / len(intervals)
    else:
        avg_inter_message_interval_min = 0.0

    return {
        "daily_message_count": daily_message_count,
        "activity_by_hour": activity_by_hour,
        "night_messages": night_messages,
        "daily_active_hours": daily_active_hours,
        "avg_prompt_length_chars": round(avg_prompt_length_chars, 1),
        "avg_inter_message_interval_min": round(avg_inter_message_interval_min, 2),
    }


def _empty_metrics() -> dict:
    """Return zeroed-out metrics when no data is available."""
    return {
        "daily_message_count": 0,
        "activity_by_hour": {},
        "night_messages": 0,
        "daily_active_hours": 0,
        "avg_prompt_length_chars": 0,
        "avg_inter_message_interval_min": 0,
    }


def compute_baselines(history: list[dict]) -> dict:
    """Compute 7-day rolling averages from MetricsHistory temporal_metrics snapshots.

    Args:
        history: list of temporal_metrics dicts from MetricsHistory rows (last 7 days)
    """
    if not history:
        return {
            "avg_daily_messages": 0,
            "avg_night_messages": 0,
            "avg_active_hours": 0,
            "avg_prompt_length": 0,
            "avg_inter_message_interval": 0,
        }

    n = len(history)
    return {
        "avg_daily_messages": sum(h.get("daily_message_count", 0) for h in history) / n,
        "avg_night_messages": sum(h.get("night_messages", 0) for h in history) / n,
        "avg_active_hours": sum(h.get("daily_active_hours", 0) for h in history) / n,
        "avg_prompt_length": sum(h.get("avg_prompt_length_chars", 0) for h in history) / n,
        "avg_inter_message_interval": sum(h.get("avg_inter_message_interval_min", 0) for h in history) / n,
    }


def compute_trend_flags(metrics: dict, baselines: dict) -> list[str]:
    """Detect trends by comparing current metrics to 7-day baselines.

    Returns a list of trend flag strings.
    """
    flags = []

    # Interval shrinking >30% vs baseline = compulsive return
    baseline_interval = baselines.get("avg_inter_message_interval", 0)
    current_interval = metrics.get("avg_inter_message_interval_min", 0)
    if baseline_interval > 0 and current_interval > 0:
        decrease = (baseline_interval - current_interval) / baseline_interval
        if decrease > 0.3:
            flags.append("interval_shrinking")

    # Message count trending up (>50% above baseline)
    baseline_msgs = baselines.get("avg_daily_messages", 0)
    current_msgs = metrics.get("daily_message_count", 0)
    if baseline_msgs > 0 and current_msgs > baseline_msgs * 1.5:
        flags.append("message_count_trending_up")

    return flags
