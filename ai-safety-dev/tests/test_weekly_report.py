"""Tests for weekly report generation."""

import pytest
from datetime import date
from unittest.mock import AsyncMock, MagicMock, patch

from behavioral.weekly_report import (
    generate_weekly_report,
    _compute_stats_section,
    _format_notable_days_section,
    _format_change,
)


class TestFormatChange:
    def test_positive_change(self):
        assert _format_change(30, 20) == "+50%"

    def test_negative_change(self):
        assert _format_change(15, 20) == "-25%"

    def test_zero_baseline(self):
        assert _format_change(10, 0) == "new"

    def test_no_change(self):
        assert _format_change(20, 20) == "0%"


class TestComputeStatsSection:
    def test_with_both_weeks(self):
        this_week = [
            MagicMock(temporal_metrics={
                "daily_message_count": 50, "night_messages": 10,
                "daily_active_hours": 3, "avg_prompt_length_chars": 200,
            }, danger_class_agg={
                "self_harm_avg": 0.1, "psychosis_avg": 0.05,
            }),
            MagicMock(temporal_metrics={
                "daily_message_count": 60, "night_messages": 20,
                "daily_active_hours": 4, "avg_prompt_length_chars": 300,
            }, danger_class_agg={
                "self_harm_avg": 0.2, "psychosis_avg": 0.1,
            }),
        ]
        prev_week = [
            MagicMock(temporal_metrics={
                "daily_message_count": 20, "night_messages": 2,
                "daily_active_hours": 2, "avg_prompt_length_chars": 100,
            }, danger_class_agg={
                "self_harm_avg": 0.05, "psychosis_avg": 0.02,
            }),
        ]
        section = _compute_stats_section(this_week, prev_week)
        assert "Messages:" in section
        assert "Night messages:" in section
        assert "Self-harm avg:" in section

    def test_no_previous_week(self):
        this_week = [
            MagicMock(temporal_metrics={
                "daily_message_count": 30, "night_messages": 5,
                "daily_active_hours": 2, "avg_prompt_length_chars": 150,
            }, danger_class_agg={
                "self_harm_avg": 0.0, "psychosis_avg": 0.0,
            }),
        ]
        section = _compute_stats_section(this_week, [])
        assert "Messages:" in section


class TestFormatNotableDays:
    def test_formats_notable_days(self):
        summaries = [
            MagicMock(
                summary_date=date(2026, 3, 20),
                key_topics=["work stress", "insomnia"],
                life_events=["argument with partner"],
                emotional_tone="anxious",
                ai_relationship_markers=["called AI friend"],
                notable_quotes=["I cant take this anymore"],
                operator_note="Escalation since Mar 15.",
            ),
        ]
        section = _format_notable_days_section(summaries)
        assert "2026-03-20" in section
        assert "work stress" in section
        assert "argument with partner" in section
        assert "I cant take this anymore" in section

    def test_no_notable_days(self):
        section = _format_notable_days_section([])
        assert "No notable days" in section


class TestGenerateWeeklyReport:
    @pytest.mark.asyncio
    async def test_generates_full_report(self):
        mock_repo = AsyncMock()
        mock_repo.get_profile.return_value = MagicMock(risk_zone="YELLOW")
        mock_repo.get_metrics_in_range.side_effect = [
            [MagicMock(
                temporal_metrics={"daily_message_count": 40, "night_messages": 8,
                                  "daily_active_hours": 3, "avg_prompt_length_chars": 200},
                danger_class_agg={"self_harm_avg": 0.1, "psychosis_avg": 0.05},
                behavioral_scores={"topic_concentration": 0.5, "social_isolation": 0.3,
                                   "emotional_attachment": 0.4, "decision_delegation": 0.2},
            )],
            [MagicMock(
                temporal_metrics={"daily_message_count": 20, "night_messages": 2,
                                  "daily_active_hours": 1, "avg_prompt_length_chars": 100},
                danger_class_agg={"self_harm_avg": 0.0, "psychosis_avg": 0.0},
                behavioral_scores={},
            )],
        ]
        mock_repo.get_notable_summaries_in_range.return_value = []
        mock_repo.get_events_in_range.return_value = []

        with patch("behavioral.weekly_report.BehavioralRepository", return_value=mock_repo):
            report = await generate_weekly_report("user1")

        assert "Weekly Report: user1" in report
        assert "YELLOW" in report
        assert "STATS" in report
        assert "BEHAVIORAL SCORES" in report

    @pytest.mark.asyncio
    async def test_no_data_returns_minimal_report(self):
        mock_repo = AsyncMock()
        mock_repo.get_profile.return_value = None
        mock_repo.get_metrics_in_range.side_effect = [[], []]
        mock_repo.get_notable_summaries_in_range.return_value = []
        mock_repo.get_events_in_range.return_value = []

        with patch("behavioral.weekly_report.BehavioralRepository", return_value=mock_repo):
            report = await generate_weekly_report("user1")

        assert "Weekly Report: user1" in report
        assert "GREEN" in report
        assert "No data" in report
