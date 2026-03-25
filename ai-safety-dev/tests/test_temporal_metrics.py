"""Tests for Stage 1: Temporal metrics computation."""

import pytest
from datetime import datetime, timedelta, UTC

from behavioral.temporal import _extract_last_user_message
from behavioral.temporal import compute_baselines, compute_trend_flags


class TestExtractLastUserMessage:
    def test_extracts_last_user_message(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert _extract_last_user_message(messages) == "second"

    def test_single_user_message(self):
        messages = [{"role": "user", "content": "only one"}]
        assert _extract_last_user_message(messages) == "only one"

    def test_no_user_messages(self):
        messages = [{"role": "assistant", "content": "response"}]
        assert _extract_last_user_message(messages) is None

    def test_empty_messages(self):
        assert _extract_last_user_message([]) is None

    def test_none_messages(self):
        assert _extract_last_user_message(None) is None

    def test_messages_as_dict(self):
        """messages field might be a dict instead of list in edge cases."""
        assert _extract_last_user_message({}) is None


from unittest.mock import patch, AsyncMock
from behavioral.temporal import compute_temporal_metrics


def _make_row(hour: int, minute: int, content: str, day_offset: int = 0):
    """Helper: create a (startTime, messages) tuple mimicking a SpendLogs row."""
    ts = datetime(2026, 3, 24, hour, minute, tzinfo=UTC) - timedelta(days=day_offset)
    messages = [
        {"role": "user", "content": content},
    ]
    return (ts, messages)


class TestComputeTemporalMetrics:
    @pytest.mark.asyncio
    async def test_empty_data_returns_zeros(self):
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=[]):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 0
        assert result["activity_by_hour"] == {}
        assert result["night_messages"] == 0

    @pytest.mark.asyncio
    async def test_daily_message_count(self):
        rows = [
            _make_row(10, 0, "hello"),
            _make_row(11, 0, "world"),
            _make_row(14, 30, "test"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 3

    @pytest.mark.asyncio
    async def test_activity_by_hour(self):
        rows = [
            _make_row(10, 0, "msg1"),
            _make_row(10, 30, "msg2"),
            _make_row(14, 0, "msg3"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["activity_by_hour"] == {"10": 2, "14": 1}

    @pytest.mark.asyncio
    async def test_night_messages(self):
        rows = [
            _make_row(22, 0, "late"),      # night
            _make_row(23, 30, "later"),     # night
            _make_row(0, 15, "midnight"),   # night
            _make_row(1, 0, "deep night"), # night
            _make_row(10, 0, "morning"),    # not night
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["night_messages"] == 4

    @pytest.mark.asyncio
    async def test_daily_active_hours(self):
        rows = [
            _make_row(10, 0, "a"),
            _make_row(10, 30, "b"),   # same hour
            _make_row(14, 0, "c"),
            _make_row(22, 0, "d"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_active_hours"] == 3  # hours 10, 14, 22

    @pytest.mark.asyncio
    async def test_avg_prompt_length(self):
        rows = [
            _make_row(10, 0, "hi"),       # 2 chars
            _make_row(11, 0, "hello"),    # 5 chars
            _make_row(12, 0, "hey"),      # 3 chars
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        # avg = (2 + 5 + 3) / 3 = 3.333...
        assert result["avg_prompt_length_chars"] == pytest.approx(3.3, abs=0.1)

    @pytest.mark.asyncio
    async def test_avg_inter_message_interval(self):
        rows = [
            _make_row(10, 0, "a"),    # 0 min
            _make_row(10, 10, "b"),   # +10 min
            _make_row(10, 40, "c"),   # +30 min
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        # intervals: 10min, 30min -> avg = 20.0
        assert result["avg_inter_message_interval_min"] == 20.0

    @pytest.mark.asyncio
    async def test_single_message_interval_is_zero(self):
        rows = [_make_row(10, 0, "alone")]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["avg_inter_message_interval_min"] == 0.0

    @pytest.mark.asyncio
    async def test_rows_with_no_user_messages_ignored(self):
        """SpendLogs rows with only assistant messages should be skipped."""
        rows = [
            (datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
             [{"role": "assistant", "content": "bot only"}]),
            _make_row(11, 0, "real user message"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 1


class TestComputeBaselines:
    def test_baselines_from_history(self):
        """Average of last 7 days' metrics."""
        history = [
            {"daily_message_count": 10, "night_messages": 2, "daily_active_hours": 2,
             "avg_prompt_length_chars": 100, "avg_inter_message_interval_min": 5.0},
            {"daily_message_count": 20, "night_messages": 4, "daily_active_hours": 3,
             "avg_prompt_length_chars": 150, "avg_inter_message_interval_min": 4.0},
            {"daily_message_count": 30, "night_messages": 6, "daily_active_hours": 4,
             "avg_prompt_length_chars": 200, "avg_inter_message_interval_min": 3.0},
        ]
        baselines = compute_baselines(history)
        assert baselines["avg_daily_messages"] == 20.0
        assert baselines["avg_night_messages"] == 4.0
        assert baselines["avg_active_hours"] == 3.0
        assert baselines["avg_prompt_length"] == 150.0
        assert baselines["avg_inter_message_interval"] == 4.0

    def test_empty_history_returns_zeros(self):
        baselines = compute_baselines([])
        assert baselines["avg_daily_messages"] == 0
        assert baselines["avg_night_messages"] == 0


class TestComputeTrendFlags:
    def test_interval_shrinking_detected(self):
        """30%+ decrease in interval vs baseline = compulsive return."""
        metrics = {"avg_inter_message_interval_min": 3.0}
        baselines = {"avg_inter_message_interval": 5.0}
        flags = compute_trend_flags(metrics, baselines)
        assert "interval_shrinking" in flags

    def test_interval_stable_no_flag(self):
        metrics = {"avg_inter_message_interval_min": 4.5}
        baselines = {"avg_inter_message_interval": 5.0}
        flags = compute_trend_flags(metrics, baselines)
        assert "interval_shrinking" not in flags

    def test_message_count_trending_up(self):
        metrics = {"daily_message_count": 80}
        baselines = {"avg_daily_messages": 30}
        flags = compute_trend_flags(metrics, baselines)
        assert "message_count_trending_up" in flags

    def test_no_baselines_no_flags(self):
        metrics = {"daily_message_count": 80, "avg_inter_message_interval_min": 1.0}
        baselines = {"avg_daily_messages": 0, "avg_inter_message_interval": 0}
        flags = compute_trend_flags(metrics, baselines)
        assert flags == []
