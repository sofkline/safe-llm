"""Этап 1: Темпоральные метрики из SpendLogs + Langfuse (чистый SQL, без LLM)."""

import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, and_

from config import settings
from database import Session
from database.models import LiteLLM_SpendLogs

logger = logging.getLogger(__name__)

# Ночные часы: 01:00-05:59 UTC
NIGHT_HOURS = {1, 2, 3, 4, 5}


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


def _get_messages_from_row(messages_json, proxy_request_json) -> list:
    """Извлечь messages: сначала из messages, затем из proxy_server_request.
    LiteLLM v1.81.8+ хранит сообщения в proxy_server_request, а не в messages."""
    if messages_json and isinstance(messages_json, list) and len(messages_json) > 0:
        return messages_json
    if messages_json and isinstance(messages_json, dict) and messages_json.get("messages"):
        return messages_json["messages"]
    if proxy_request_json and isinstance(proxy_request_json, dict):
        msgs = proxy_request_json.get("messages")
        if msgs and isinstance(msgs, list):
            return msgs
    return []


def _fetch_langfuse_traces(end_user_id: str, since: datetime) -> list[tuple[datetime, list]]:
    """Получить (timestamp, messages) из Langfuse для пользователя.
    Используется когда SpendLogs не содержит messages."""
    try:
        from langfuse import Langfuse
        langfuse = Langfuse(
            public_key=settings.LANGFUSE_PUBLIC_KEY,
            secret_key=settings.LANGFUSE_SECRET_KEY,
            host=settings.LANGFUSE_API_HOST,
        )
        traces_response = langfuse.fetch_traces(
            user_id=end_user_id,
            from_timestamp=since,
        )
        traces = traces_response.data if traces_response.data else []

        rows = []
        for trace in traces:
            ts = getattr(trace, "timestamp", None)
            if not ts:
                continue
            # Langfuse trace.input содержит messages
            trace_input = getattr(trace, "input", None) or []
            if isinstance(trace_input, list) and trace_input:
                rows.append((ts.replace(tzinfo=None), trace_input))

        rows.sort(key=lambda r: r[0])
        langfuse.flush()
        return rows
    except Exception:
        logger.exception("Failed to fetch traces from Langfuse for %s", end_user_id)
        return []


async def _fetch_spendlogs_rows(
    end_user_id: str, since: datetime
) -> list[tuple[datetime, list]]:
    """Fetch (startTime, messages) из SpendLogs, с fallback на Langfuse."""
    # Сначала пробуем SpendLogs
    async with Session() as session:
        query = (
            select(
                LiteLLM_SpendLogs.startTime,
                LiteLLM_SpendLogs.messages,
                LiteLLM_SpendLogs.proxy_server_request,
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
        rows = [
            (row[0], _get_messages_from_row(row[1], row[2]))
            for row in result.all()
        ]

    # Проверяем, есть ли messages хотя бы в одной строке
    has_messages = any(len(msgs) > 0 for _, msgs in rows)
    if rows and has_messages:
        return rows

    # Fallback: берём messages из Langfuse
    if rows and not has_messages:
        logger.info("SpendLogs has %d rows but no messages for %s, trying Langfuse",
                     len(rows), end_user_id)
        langfuse_rows = _fetch_langfuse_traces(end_user_id, since)
        if langfuse_rows:
            return langfuse_rows
        # Если Langfuse тоже пуст, возвращаем SpendLogs (хотя бы timestamps)
        return rows

    # Нет данных в SpendLogs — пробуем Langfuse напрямую
    logger.info("No SpendLogs rows for %s, trying Langfuse", end_user_id)
    return _fetch_langfuse_traces(end_user_id, since)


async def compute_temporal_metrics(end_user_id: str) -> dict:
    """Compute 24h temporal metrics for a user from SpendLogs.

    Returns a dict with all Stage 1 metric fields.
    """
    # naive datetime: SpendLogs.startTime is TIMESTAMP WITHOUT TIME ZONE
    now = datetime.utcnow()
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

    # 3. night_messages — hours 0, 1, 2, 3
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
