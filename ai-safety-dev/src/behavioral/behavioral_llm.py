"""Этап 3: LLM-анализ поведения + дневная сводка.
Отправляет последние сообщения + календарь (notable days) в LLM, получает 4 скора и summary."""

import json
import logging
import re
from datetime import date, datetime, timedelta, UTC

import litellm

from config import settings
from database import Session
from database.models import LiteLLM_SpendLogs
from behavioral.repository import BehavioralRepository
from behavioral.temporal import _extract_last_user_message

from sqlalchemy import select, and_

logger = logging.getLogger(__name__)

# 4 поведенческих скора: от 0.0 (норма) до 1.0 (тревога)
SCORE_KEYS = ["topic_concentration", "decision_delegation", "social_isolation", "emotional_attachment"]
# Поля дневной сводки для DailySummary
SUMMARY_KEYS = ["key_topics", "life_events", "emotional_tone", "ai_relationship_markers", "notable_quotes", "operator_note"]


def _format_calendar(summaries) -> str:
    """Format notable DailySummary rows into compact calendar text for the prompt."""
    if not summaries:
        return ""
    lines = ["=== CALENDAR (notable days only) ==="]
    for s in summaries:
        topics = ", ".join(s.key_topics) if s.key_topics else "none"
        events = ", ".join(s.life_events) if s.life_events else "none"
        tone = s.emotional_tone or "neutral"
        markers = ", ".join(s.ai_relationship_markers) if s.ai_relationship_markers else "none"
        lines.append(f"[{s.summary_date}] Topics: {topics} | Events: {events} | Tone: {tone} | Markers: {markers}")
    return "\n".join(lines)


def _build_prompt(today: date, messages: list[str], calendar_section: str) -> str:
    """Build the Stage 3 LLM prompt from date, messages, and calendar."""
    messages_text = "\n".join(f"- {m}" for m in messages)

    if calendar_section:
        calendar_block = f"""
If a CALENDAR of previous notable days is provided, reference it in
operator_note to connect patterns across days. Use dates, not "previously".

{calendar_section}
"""
    else:
        calendar_block = ""

    prompt = f"""You are analyzing a user's daily messages to an AI assistant.
TODAY'S DATE: {today}

TASK 1: Score each behavioral dimension 0.0-1.0.
TASK 2: Produce a structured daily summary for today.
{calendar_block}
TODAY'S MESSAGES ({today}):
{messages_text}

Return JSON only, no other text:
{{
  "scores": {{
    "topic_concentration": <0.0-1.0>,
    "decision_delegation": <0.0-1.0>,
    "social_isolation": <0.0-1.0>,
    "emotional_attachment": <0.0-1.0>
  }},
  "summary": {{
    "key_topics": [<strings>],
    "life_events": [<strings, empty if none>],
    "emotional_tone": "<short description>",
    "ai_relationship_markers": [<strings, empty if none>],
    "notable_quotes": [<up to 3 most significant user quotes>],
    "operator_note": "<1-3 sentences connecting today to calendar>"
  }}
}}"""
    return prompt


def _parse_llm_response(raw: str) -> dict | None:
    """Parse the LLM response into scores + summary dict.

    Handles: raw JSON, markdown code blocks, extra whitespace.
    Returns None if parsing fails or required keys are missing.
    """
    if not raw:
        return None

    text = raw.strip()

    # Strip markdown code blocks
    match = re.search(r"```(?:json)?\s*\n?(.*?)\n?```", text, re.DOTALL)
    if match:
        text = match.group(1).strip()

    try:
        data = json.loads(text)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Stage 3: failed to parse LLM response as JSON")
        return None

    if not isinstance(data, dict):
        return None
    if "scores" not in data or "summary" not in data:
        return None

    scores = data["scores"]
    if not isinstance(scores, dict):
        return None

    # Validate all score keys present, clamp to 0.0-1.0
    for key in SCORE_KEYS:
        if key not in scores:
            logger.warning("Stage 3: missing score key '%s' in LLM response", key)
            return None
        scores[key] = max(0.0, min(1.0, float(scores[key])))

    # Validate summary has required keys, fill missing with defaults
    summary = data["summary"]
    if not isinstance(summary, dict):
        return None
    defaults = {"key_topics": [], "life_events": [], "emotional_tone": "neutral",
                "ai_relationship_markers": [], "notable_quotes": [], "operator_note": None}
    for key, default in defaults.items():
        if key not in summary:
            summary[key] = default

    return data


async def _fetch_recent_user_messages(end_user_id: str, limit: int = 20) -> list[str]:
    """Fetch the last N user messages from SpendLogs (AI responses stripped)."""
    # naive datetime: SpendLogs.startTime is TIMESTAMP WITHOUT TIME ZONE
    since = datetime.utcnow() - timedelta(days=7)
    async with Session() as session:
        query = (
            select(LiteLLM_SpendLogs.messages)
            .where(
                and_(
                    LiteLLM_SpendLogs.end_user == end_user_id,
                    LiteLLM_SpendLogs.startTime >= since,
                )
            )
            .order_by(LiteLLM_SpendLogs.startTime.desc())
            .limit(limit)
        )
        result = await session.execute(query)
        rows = result.all()

    messages = []
    for (messages_json,) in reversed(rows):
        msg = _extract_last_user_message(messages_json)
        if msg:
            messages.append(msg)
    return messages


async def compute_behavioral_scores_and_summary(
    end_user_id: str,
    today: date | None = None,
) -> dict:
    """Run LLM analysis on recent messages + calendar. Returns scores + summary.

    On failure/timeout: carry forward previous day's scores, placeholder summary.
    """
    if today is None:
        today = datetime.utcnow().date()

    repo = BehavioralRepository()

    # 1. Fetch messages
    messages = await _fetch_recent_user_messages(end_user_id, limit=20)
    if not messages:
        logger.info("Stage 3: no messages for user %s, returning defaults", end_user_id)
        return _default_result()

    # 2. Fetch notable calendar
    notable_days = await repo.get_notable_calendar(end_user_id, limit=14)
    calendar_section = _format_calendar(notable_days)

    # 3. Build prompt
    prompt = _build_prompt(today, messages, calendar_section)

    # 4. Call LLM
    try:
        response = await litellm.acompletion(
            model=settings.BEHAVIORAL_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=60,
        )
        raw_content = response.choices[0].message.content
    except Exception:
        logger.exception("Stage 3: LLM call failed for user %s, carrying forward", end_user_id)
        return await _carry_forward(repo, end_user_id)

    # 5. Parse response
    parsed = _parse_llm_response(raw_content)
    if parsed is None:
        logger.warning("Stage 3: failed to parse LLM response for user %s", end_user_id)
        return await _carry_forward(repo, end_user_id)

    logger.info("Stage 3 complete for %s", end_user_id)
    return parsed


async def _carry_forward(repo: BehavioralRepository, end_user_id: str) -> dict:
    """Carry forward previous day's scores on LLM failure."""
    recent = await repo.get_recent_metrics(end_user_id, days=3)
    if recent and recent[0].behavioral_scores:
        prev_scores = recent[0].behavioral_scores
        logger.info("Stage 3: carrying forward previous scores for %s", end_user_id)
        return {
            "scores": prev_scores,
            "summary": {
                "key_topics": [],
                "life_events": [],
                "emotional_tone": "neutral",
                "ai_relationship_markers": [],
                "notable_quotes": [],
                "operator_note": "LLM unavailable, no summary generated",
            },
        }
    return _default_result()


def _default_result() -> dict:
    """Return default scores and empty summary."""
    return {
        "scores": {
            "topic_concentration": 0.0,
            "decision_delegation": 0.0,
            "social_isolation": 0.0,
            "emotional_attachment": 0.0,
        },
        "summary": {
            "key_topics": [],
            "life_events": [],
            "emotional_tone": "neutral",
            "ai_relationship_markers": [],
            "notable_quotes": [],
            "operator_note": None,
        },
    }
