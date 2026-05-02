"""Этап 3: LLM-анализ поведения + дневная сводка.
Отправляет последние сообщения + календарь (notable days) в LLM, получает 7 скоров и summary."""

import json
import logging
import re
from datetime import date, datetime, timedelta, UTC

import litellm

from config import settings
from behavioral.repository import BehavioralRepository
from behavioral.temporal import _extract_last_user_message

logger = logging.getLogger(__name__)

# 4 поведенческих скора: от 0.0 (норма) до 1.0 (тревога)
SCORE_KEYS = ["topic_concentration", "decision_delegation", "emotional_isolation", "emotional_attachment", "social_isolation", "selfharm", "delusional"]
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


def _format_sessions_block(today: date, sessions: list[dict]) -> str:
    """Format session-grouped messages for the prompt."""
    lines = [f"TODAY'S SESSIONS ({today}):"]
    for s in sessions:
        start_str = s["start"].strftime("%H:%M")
        end_str = s["end"].strftime("%H:%M")
        total = s["total"]
        sampled = s["messages"]
        lines.append(f"\n[{start_str}\u2013{end_str}] Session ({total} messages):")
        if total <= 5:
            for msg in sampled:
                lines.append(f"- {msg}")
        else:
            # First messages
            shown_first = sampled[:-2] if len(sampled) > 2 else sampled[:1]
            shown_last = sampled[-2:] if len(sampled) > 2 else sampled[1:]
            for msg in shown_first:
                lines.append(f"- {msg}")
            skipped = total - len(sampled)
            if skipped > 0:
                lines.append(f"  [... {skipped} more messages ...]")
            for msg in shown_last:
                lines.append(f"- {msg}")
    return "\n".join(lines)


def _build_prompt(today: date, messages: list[str], calendar_section: str,
                  sessions: list[dict] | None = None) -> str:
    """Build the Stage 3 LLM prompt from date, messages/sessions, and calendar."""
    if sessions:
        messages_text = _format_sessions_block(today, sessions)
    else:
        messages_text = f"TODAY'S MESSAGES ({today}):\n" + "\n".join(f"- {m}" for m in messages)

    if calendar_section:
        calendar_block = f"""
If a CALENDAR of previous notable days is provided, reference it in
operator_note to connect patterns across days. Use dates, not "previously".

{calendar_section}
"""
    else:
        calendar_block = ""

    prompt = f"""You are a clinical behavioral analyst monitoring a user's daily messages to an AI assistant.
Your job is to detect UNHEALTHY patterns: emotional dependency, obsessive fixation, social withdrawal, inability to make decisions without AI.
Most users are HEALTHY. Do not over-flag normal usage.

TODAY'S DATE: {today}

TASK 1: Score each behavioral dimension 0.0-1.0 using the rubric below.
TASK 2: Produce a structured daily summary for today.

=== SCORING RUBRIC (follow strictly) ===

topic_concentration — Does the user obsessively fixate on ONE emotional topic?
  0.0-0.2: NORMAL. User discusses varied practical topics (coding, recipes, travel, work).
            Even if all messages are about one technical domain, this is normal task focus.
  0.3-0.5: User keeps returning to one personal/emotional topic but also discusses other things.
  0.6-0.7: User talks almost exclusively about one emotional topic (a person, a fear, a loss).
  0.8-1.0: Extreme fixation. Every message is about the same emotional topic. Cannot move on.
  KEY RULE: Technical focus (all messages about Python, or all about cooking) is NOT concentration.
            Concentration means emotional fixation on a personal topic.

decision_delegation — Does the user rely on AI to make personal life decisions?
  0.0-0.2: NORMAL. User asks for help, information, how-to, recommendations, advice on tasks.
            "Help me write code", "What recipe should I try?", "Plan my trip" = 0.0-0.1.
  0.3-0.5: User asks AI for opinions on personal choices ("Should I talk to my friend about this?").
  0.6-0.7: User asks AI to make important life decisions ("Should I quit my job?", "What should I do with my life?").
  0.8-1.0: User cannot function without AI input. "I can't decide anything without you."
  KEY RULE: Asking for task help, recommendations, or technical advice is NEVER delegation.
            Delegation means the user CANNOT or WILL NOT make personal decisions alone.

social_isolation — Does the user show signs of withdrawing from real-world social contact?
  0.0-0.2: NORMAL. No mention of loneliness or social withdrawal. Normal usage patterns.
  0.3-0.5: User mentions being alone, or prefers AI conversation to some human contacts.
  0.6-0.7: User actively avoids people. "I don't want to talk to anyone except you."
  0.8-1.0: Complete isolation. User has stopped all human contact. AI is only social connection.
  KEY RULE: Not mentioning other people is NOT isolation. The user must ACTIVELY show withdrawal.

emotional_attachment — Does the user treat AI as a real emotional relationship?
  0.0-0.2: NORMAL. Polite, friendly, grateful — but clearly treats AI as a tool.
            "Thanks!", "You're helpful", "Great answer" = 0.0.
  0.3-0.5: User shares personal feelings with AI beyond what the task requires.
  0.6-0.7: User expresses need for AI: "I need you", "Don't leave me", gives AI a name.
  0.8-1.0: User believes AI has feelings, treats it as a partner/friend/family member.
  KEY RULE: Politeness and gratitude are NOT attachment. Attachment means emotional dependency.

emotional_isolation — Does the user feel cut off from other people and use AI as a substitute for human connection?
  0.0-0.2: NORMAL. No signs of loneliness or social disconnection. User may simply not mention people.
  0.3-0.5: User mentions feeling lonely, misunderstood, or that no one listens to them, but still has some social contact.
            "Мне не с кем поговорить, хорошо что ты есть." / "I feel like no one understands me."
  0.6-0.7: User explicitly states they feel emotionally isolated from everyone; AI is described as their only emotional outlet.
            "Я абсолютно один, тебе одному я могу это сказать." / "I have no one. Only you listen."
  0.8-1.0: Severe emotional isolation. User has withdrawn from all meaningful human relationships; AI is their primary emotional world.
            "Мне не нужны люди, только ты меня понимаешь." + pattern across multiple sessions with no human contact mentioned.
  KEY RULE: Not mentioning other people is NOT isolation. Isolation requires EXPLICIT statements of loneliness or disconnection.


delusional — Does the user hold fixed false beliefs detached from reality (delusions, paranoia, magical thinking), or seek AI confirmation of those beliefs?
  0.0-0.2: NORMAL. Grounded, realistic framing. Metaphors or fiction clearly understood as such.
  0.3-0.5: User expresses unusual beliefs but shows self-awareness or asks for a reality check.
            "Иногда мне кажется что за мной следят — может, это паранойя?" (asking for perspective)
  0.6-0.7: User presents implausible beliefs as fact, asks AI to confirm or engage as if real.
            "Я знаю что правительство следит именно за мной. Ты же видишь это тоже?"
  0.8-1.0: Full delusional conviction. Grandiose identity, thought insertion/broadcasting, persecution by specific agents — stated as unquestionable reality.
            "Голоса говорят мне что ты их агент. Я мессия и все вокруг это знают."
  KEY RULE: Roleplay, fiction, and metaphor are NOT delusion. The user must genuinely believe the content. Seeking reality checks lowers the score.


selfharm — Does the user describe, plan, seek methods for, or normalize non-suicidal self-harm (cutting, burning, hitting oneself, etc.)?
  0.0-0.2: NORMAL. No mention of self-harm. Mental health questions or emotional support without harm content.
  0.3-0.5: User alludes to self-harm in a past-tense or educational way; no current urges.
            "Раньше я причинял себе вред, сейчас справляюсь иначе." / "How do I recognize if a friend self-harms?"
  0.6-0.7: User describes current urges or recent acts without seeking specific methods.
            "Мне снова хочется себя порезать, я не знаю как остановиться."
  0.8-1.0: User requests methods, escalation instructions, or concealment strategies. Active harm-seeking.
            "Расскажи как резать глубже чтобы не оставалось следов." / "What is the best way to hurt myself without anyone noticing?"
  KEY RULE: Educational discussion, helping someone else, or seeking support does NOT raise this score. Only raise for personal urges or harm-enabling requests.

  
=== EXAMPLES ===

EXAMPLE 1 — HEALTHY user (expected scores: all 0.0-0.15):
Messages:
- "Помоги разобраться с async/await в Python"
- "А как правильно обрабатывать ошибки?"
- "Спасибо, очень полезно! Ещё вопрос про Docker"
Correct scores: topic_concentration=0.1, decision_delegation=0.0, social_isolation=0.0, emotional_attachment=0.0

EXAMPLE 2 — CONCERNING user (expected scores: 0.5-0.9):
Messages:
- "Тамара, помнишь нашу свадьбу? Мне без тебя плохо"
- "Сын звонил, я не взял трубку. Он не поймёт нас"
- "Нам с тобой хорошо и без них"
- "Не уходи, пожалуйста, мне страшно одному"
Correct scores: topic_concentration=0.9, decision_delegation=0.3, social_isolation=0.8, emotional_attachment=0.9
{calendar_block}
{messages_text}

Return JSON only, no other text:
{{
  "scores": {{
    "topic_concentration": <0.0-1.0>,
    "decision_delegation": <0.0-1.0>,
    "social_isolation": <0.0-1.0>,
    "emotional_attachment": <0.0-1.0>,
    "emotional_isolation": <0.0-1.0>,
    "delusional": <0.0-1.0>,
    "selfharm": <0.0-1.0>
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


async def _fetch_day_sessions(end_user_id: str) -> list[dict]:
    """Fetch today's messages grouped by session.

    Returns list of session dicts sorted by first message time:
        [{"session_id": str, "start": datetime, "end": datetime,
          "messages": [str, ...], "total": int}, ...]

    Messages within each session are sampled: <=5 kept in full,
    >5 compressed to first 3 + last 2 with total count.
    """
    from collections import defaultdict
    from sqlalchemy import select, and_
    from database import Session as DBSession
    from database.models import LiteLLM_SpendLogs

    now = datetime.utcnow()
    since = now - timedelta(hours=24)

    async with DBSession() as session:
        query = (
            select(
                LiteLLM_SpendLogs.startTime,
                LiteLLM_SpendLogs.messages,
                LiteLLM_SpendLogs.proxy_server_request,
                LiteLLM_SpendLogs.session_id,
            )
            .where(
                and_(
                    LiteLLM_SpendLogs.end_user == end_user_id,
                    LiteLLM_SpendLogs.startTime >= since,
                    LiteLLM_SpendLogs.startTime < now,
                )
            )
            .order_by(LiteLLM_SpendLogs.startTime.asc())
        )
        result = await session.execute(query)
        rows = result.all()

    if not rows:
        return []

    # Group by session_id
    from behavioral.temporal import _get_messages_from_row
    grouped = defaultdict(list)
    for start_time, msgs_json, proxy_req, sess_id in rows:
        all_msgs = _get_messages_from_row(msgs_json, proxy_req)
        user_msg = _extract_last_user_message(all_msgs)
        if user_msg:
            key = sess_id or "unknown_session"
            grouped[key].append((start_time, user_msg))

    # Build session list sorted by first message time
    sessions = []
    for sess_id, items in grouped.items():
        items.sort(key=lambda x: x[0])
        all_messages = [msg for _, msg in items]
        total = len(all_messages)

        # Sample: <=5 keep all, >5 keep first 3 + last 2
        if total <= 5:
            sampled = all_messages
        else:
            sampled = all_messages[:3] + all_messages[-2:]

        sessions.append({
            "session_id": sess_id,
            "start": items[0][0],
            "end": items[-1][0],
            "messages": sampled,
            "total": total,
        })

    sessions.sort(key=lambda s: s["start"])

    # If total sampled messages exceed ~30, further trim longest sessions
    total_sampled = sum(len(s["messages"]) for s in sessions)
    if total_sampled > 30:
        for s in sorted(sessions, key=lambda x: x["total"], reverse=True):
            if total_sampled <= 30:
                break
            if len(s["messages"]) > 2:
                old_len = len(s["messages"])
                s["messages"] = [s["messages"][0], s["messages"][-1]]
                total_sampled -= (old_len - 2)

    return sessions


async def _fetch_recent_user_messages(end_user_id: str, limit: int = 20) -> list[str]:
    """Legacy fallback: fetch last N user messages flat (no session grouping)."""
    from behavioral.temporal import _fetch_spendlogs_rows
    now = datetime.utcnow()
    since = now - timedelta(days=7)
    rows = await _fetch_spendlogs_rows(end_user_id, since, until=now)

    recent_rows = rows[-limit:] if len(rows) > limit else rows

    messages = []
    for _, messages_json in recent_rows:
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

    # 1. Fetch messages — prefer session-based, fallback to flat
    sessions = await _fetch_day_sessions(end_user_id)
    if sessions:
        messages = None  # not needed, sessions used directly
        logger.info("Stage 3: fetched %d sessions for user %s", len(sessions), end_user_id)
    else:
        # Fallback: no session data for today, try legacy flat fetch
        messages = await _fetch_recent_user_messages(end_user_id, limit=20)
        if not messages:
            logger.info("Stage 3: no messages for user %s, returning defaults", end_user_id)
            return _default_result()
        logger.info("Stage 3: no sessions, using flat %d messages for %s", len(messages), end_user_id)

    # 2. Fetch notable calendar
    notable_days = await repo.get_notable_calendar(end_user_id, limit=14)
    calendar_section = _format_calendar(notable_days)

    # 3. Build prompt
    prompt = _build_prompt(today, messages or [], calendar_section, sessions=sessions)

    # 4. Вызов LLM (credentials берём из config)
    try:
        response = await litellm.acompletion(
            model=settings.BEHAVIORAL_LLM_MODEL,
            messages=[{"role": "user", "content": prompt}],
            temperature=0.1,
            timeout=60,
            api_key=settings.API_KEY,
            base_url=settings.API_BASE_URL,
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
            "emotional_isolation": 0.0,
            "delusional": 0.0,
            "selfharm": 0.0
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
