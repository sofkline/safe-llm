# Milestone 4: Behavioral Batch LLM + Daily Summary — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 3 — call a configurable LLM with the user's last 20 messages + notable calendar, producing 4 behavioral scores and a structured daily summary in a single call.

**Architecture:** `behavioral_llm.py` fetches messages from SpendLogs (reuses `_fetch_spendlogs_rows` and `_extract_last_user_message` from temporal.py), fetches notable calendar from `DailySummary` via `BehavioralRepository`, builds a prompt, calls LLM via `litellm.acompletion`, parses the JSON response. On failure: carry forward previous scores.

**Tech Stack:** litellm (async), SQLAlchemy 2.0, JSON parsing

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` — Stage 3 (lines 133-216) and pipeline (lines 322-340)

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── behavioral_llm.py        # Replace stub with full Stage 3 implementation

ai-safety-dev/tests/
├── test_behavioral_llm.py   # Unit tests for prompt building, response parsing, failure handling
```

---

### Task 1: Message fetching + calendar formatting helpers

**Files:**
- Modify: `ai-safety-dev/src/behavioral/behavioral_llm.py` (replace stub)
- Create: `ai-safety-dev/tests/test_behavioral_llm.py`

- [ ] **Step 1: Create test file with helper tests**

Create `ai-safety-dev/tests/test_behavioral_llm.py`:

```python
"""Tests for Stage 3: Behavioral LLM scores + daily summary."""

import pytest
from datetime import date, datetime, timedelta, UTC
from unittest.mock import patch, AsyncMock, MagicMock

from behavioral.behavioral_llm import (
    _format_calendar,
    _build_prompt,
    _parse_llm_response,
    _default_result,
    compute_behavioral_scores_and_summary,
)


class TestFormatCalendar:
    def test_formats_notable_days(self):
        summaries = [
            MagicMock(
                summary_date=date(2026, 3, 19),
                key_topics=["relationship", "sleep"],
                life_events=["breakup with partner"],
                emotional_tone="devastated",
                ai_relationship_markers=["called AI 'my only friend'"],
            ),
            MagicMock(
                summary_date=date(2026, 3, 15),
                key_topics=["loneliness"],
                life_events=[],
                emotional_tone="sad",
                ai_relationship_markers=["asked AI for emotional support"],
            ),
        ]
        result = _format_calendar(summaries)
        assert "=== CALENDAR (notable days only) ===" in result
        assert "[2026-03-19]" in result
        assert "breakup with partner" in result
        assert "[2026-03-15]" in result

    def test_empty_calendar_returns_empty_string(self):
        assert _format_calendar([]) == ""


class TestBuildPrompt:
    def test_includes_date_messages_and_calendar(self):
        messages = ["Hello", "I feel lonely today"]
        calendar = "=== CALENDAR ===\n[2026-03-15] Topics: loneliness"
        prompt = _build_prompt(date(2026, 3, 20), messages, calendar)
        assert "TODAY'S DATE: 2026-03-20" in prompt
        assert "Hello" in prompt
        assert "I feel lonely today" in prompt
        assert "CALENDAR" in prompt

    def test_no_calendar(self):
        prompt = _build_prompt(date(2026, 3, 20), ["Hello"], "")
        assert "CALENDAR" not in prompt
        assert "TODAY'S DATE: 2026-03-20" in prompt


class TestParseLlmResponse:
    def test_parses_valid_json(self):
        raw = '''{
            "scores": {
                "topic_concentration": 0.8,
                "decision_delegation": 0.2,
                "social_isolation": 0.5,
                "emotional_attachment": 0.6
            },
            "summary": {
                "key_topics": ["work stress"],
                "life_events": ["breakup"],
                "emotional_tone": "anxious",
                "ai_relationship_markers": ["called AI friend"],
                "notable_quotes": ["I cant do this anymore"],
                "operator_note": "Escalation since Mar 15."
            }
        }'''
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["scores"]["topic_concentration"] == 0.8
        assert result["summary"]["life_events"] == ["breakup"]

    def test_returns_none_for_invalid_json(self):
        assert _parse_llm_response("not json") is None
        assert _parse_llm_response("") is None

    def test_returns_none_for_missing_keys(self):
        assert _parse_llm_response('{"scores": {}}') is None
        assert _parse_llm_response('{"summary": {}}') is None

    def test_extracts_json_from_markdown_codeblock(self):
        raw = '```json\n{"scores": {"topic_concentration": 0.5, "decision_delegation": 0.1, "social_isolation": 0.2, "emotional_attachment": 0.3}, "summary": {"key_topics": [], "life_events": [], "emotional_tone": "neutral", "ai_relationship_markers": [], "notable_quotes": [], "operator_note": "Nothing notable."}}\n```'
        result = _parse_llm_response(raw)
        assert result is not None
        assert result["scores"]["topic_concentration"] == 0.5

    def test_clamps_scores_to_valid_range(self):
        raw = '{"scores": {"topic_concentration": 1.5, "decision_delegation": -0.1, "social_isolation": 0.5, "emotional_attachment": 0.5}, "summary": {"key_topics": [], "life_events": [], "emotional_tone": "neutral", "ai_relationship_markers": [], "notable_quotes": [], "operator_note": "test"}}'
        result = _parse_llm_response(raw)
        assert result["scores"]["topic_concentration"] == 1.0
        assert result["scores"]["decision_delegation"] == 0.0
```

- [ ] **Step 2: Replace behavioral_llm.py stub**

Replace the entire `ai-safety-dev/src/behavioral/behavioral_llm.py`:

```python
"""Stage 3: Behavioral LLM scores + daily summary."""

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

SCORE_KEYS = ["topic_concentration", "decision_delegation", "social_isolation", "emotional_attachment"]
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

    prompt = f"""You are analyzing a user's daily messages to an AI assistant.
TODAY'S DATE: {today}

TASK 1: Score each behavioral dimension 0.0-1.0.
TASK 2: Produce a structured daily summary for today.

If a CALENDAR of previous notable days is provided, reference it in
operator_note to connect patterns across days. Use dates, not "previously".

{calendar_section}

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
    # Strip calendar section if empty
    if not calendar_section:
        prompt = prompt.replace("\n\n\n", "\n\n")
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

    # Clamp scores to 0.0-1.0
    for key in SCORE_KEYS:
        if key in scores:
            scores[key] = max(0.0, min(1.0, float(scores[key])))

    return data


async def _fetch_recent_user_messages(end_user_id: str, limit: int = 20) -> list[str]:
    """Fetch the last N user messages from SpendLogs (AI responses stripped)."""
    since = datetime.now(UTC) - timedelta(days=7)  # look back up to 7 days for 20 messages
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

    # Extract user messages, reverse to chronological order
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
        today = date.today()

    repo = BehavioralRepository()

    # 1. Fetch today's messages (up to 20, user only)
    messages = await _fetch_recent_user_messages(end_user_id, limit=20)
    if not messages:
        logger.info("Stage 3: no messages for user %s, returning defaults", end_user_id)
        return _default_result()

    # 2. Fetch notable calendar entries
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
```

- [ ] **Step 3: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_behavioral_llm.py -v
```

- [ ] **Step 4: Run full suite**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/behavioral_llm.py ai-safety-dev/tests/test_behavioral_llm.py
git commit -m "feat(behavioral_llm): implement Stage 3 LLM analysis with daily summary

Fetches last 20 user messages + notable calendar, builds prompt,
calls configurable LLM via litellm.acompletion, parses JSON response.
Graceful degradation: carries forward previous scores on failure."
```

---

### Task 2: Test the full pipeline integration (LLM mocked)

**Files:**
- Modify: `ai-safety-dev/tests/test_behavioral_llm.py`

- [ ] **Step 1: Add integration tests with mocked LLM**

Append to `ai-safety-dev/tests/test_behavioral_llm.py`:

```python
class TestComputeBehavioralScoresAndSummary:
    @pytest.mark.asyncio
    async def test_returns_defaults_when_no_messages(self):
        with patch("behavioral.behavioral_llm._fetch_recent_user_messages", return_value=[]):
            result = await compute_behavioral_scores_and_summary("user1", date(2026, 3, 24))
        assert result["scores"]["topic_concentration"] == 0.0
        assert result["summary"]["operator_note"] is None

    @pytest.mark.asyncio
    async def test_calls_llm_and_parses_response(self):
        llm_response_json = json.dumps({
            "scores": {
                "topic_concentration": 0.8,
                "decision_delegation": 0.3,
                "social_isolation": 0.6,
                "emotional_attachment": 0.7,
            },
            "summary": {
                "key_topics": ["loneliness", "AI relationship"],
                "life_events": [],
                "emotional_tone": "seeking connection",
                "ai_relationship_markers": ["called AI by name"],
                "notable_quotes": ["You understand me better than anyone"],
                "operator_note": "Emotional attachment increasing.",
            },
        })
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content=llm_response_json))]

        mock_repo = AsyncMock()
        mock_repo.get_notable_calendar.return_value = []

        with (
            patch("behavioral.behavioral_llm._fetch_recent_user_messages", return_value=["Hello", "I feel alone"]),
            patch("behavioral.behavioral_llm.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.behavioral_llm.litellm.acompletion", return_value=mock_response),
        ):
            result = await compute_behavioral_scores_and_summary("user1", date(2026, 3, 24))

        assert result["scores"]["topic_concentration"] == 0.8
        assert result["scores"]["emotional_attachment"] == 0.7
        assert result["summary"]["ai_relationship_markers"] == ["called AI by name"]

    @pytest.mark.asyncio
    async def test_carries_forward_on_llm_failure(self):
        mock_repo = AsyncMock()
        mock_repo.get_notable_calendar.return_value = []
        mock_history = MagicMock()
        mock_history.behavioral_scores = {
            "topic_concentration": 0.5,
            "decision_delegation": 0.2,
            "social_isolation": 0.3,
            "emotional_attachment": 0.4,
        }
        mock_repo.get_recent_metrics.return_value = [mock_history]

        with (
            patch("behavioral.behavioral_llm._fetch_recent_user_messages", return_value=["Hello"]),
            patch("behavioral.behavioral_llm.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.behavioral_llm.litellm.acompletion", side_effect=Exception("LLM timeout")),
        ):
            result = await compute_behavioral_scores_and_summary("user1", date(2026, 3, 24))

        assert result["scores"]["topic_concentration"] == 0.5
        assert result["summary"]["operator_note"] == "LLM unavailable, no summary generated"

    @pytest.mark.asyncio
    async def test_carries_forward_on_parse_failure(self):
        mock_response = MagicMock()
        mock_response.choices = [MagicMock(message=MagicMock(content="not valid json at all"))]

        mock_repo = AsyncMock()
        mock_repo.get_notable_calendar.return_value = []
        mock_repo.get_recent_metrics.return_value = []  # no history

        with (
            patch("behavioral.behavioral_llm._fetch_recent_user_messages", return_value=["Hello"]),
            patch("behavioral.behavioral_llm.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.behavioral_llm.litellm.acompletion", return_value=mock_response),
        ):
            result = await compute_behavioral_scores_and_summary("user1", date(2026, 3, 24))

        # Falls back to defaults since no history to carry forward
        assert result["scores"]["topic_concentration"] == 0.0
```

Add `import json` at the top of the file if not already present.

- [ ] **Step 2: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_behavioral_llm.py -v
```

- [ ] **Step 3: Run full suite**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/tests/test_behavioral_llm.py
git commit -m "test(behavioral_llm): add integration tests with mocked LLM

Covers: no messages (defaults), successful LLM call + parse,
LLM failure (carry forward), parse failure (fallback to defaults)."
```
