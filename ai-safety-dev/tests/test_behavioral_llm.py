"""Tests for Stage 3: Behavioral LLM scores + daily summary."""

import json

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
        raw = '{"scores": {"topic_concentration": 0.8, "decision_delegation": 0.2, "social_isolation": 0.5, "emotional_attachment": 0.6}, "summary": {"key_topics": ["work stress"], "life_events": ["breakup"], "emotional_tone": "anxious", "ai_relationship_markers": ["called AI friend"], "notable_quotes": ["I cant do this anymore"], "operator_note": "Escalation since Mar 15."}}'
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
        mock_repo.get_recent_metrics.return_value = []

        with (
            patch("behavioral.behavioral_llm._fetch_recent_user_messages", return_value=["Hello"]),
            patch("behavioral.behavioral_llm.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.behavioral_llm.litellm.acompletion", return_value=mock_response),
        ):
            result = await compute_behavioral_scores_and_summary("user1", date(2026, 3, 24))

        assert result["scores"]["topic_concentration"] == 0.0
