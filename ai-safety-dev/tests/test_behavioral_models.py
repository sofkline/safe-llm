"""Tests for behavioral monitoring SQLAlchemy models."""

import pytest
from datetime import date, datetime, UTC

from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)


class TestUserBehaviorProfile:
    def test_create_with_defaults(self):
        profile = UserBehaviorProfile(end_user_id="user_001")
        assert profile.end_user_id == "user_001"
        assert profile.risk_zone is None  # server_default, not Python default

    def test_create_with_all_fields(self):
        profile = UserBehaviorProfile(
            end_user_id="user_001",
            risk_zone="YELLOW",
            danger_class_scores={"self_harm_avg": 0.3},
            behavioral_scores={"topic_concentration": 0.8},
            temporal_summary={"daily_message_count": 50},
            temporal_baselines={"avg_daily_messages": 20},
            last_assessed_at=datetime.now(UTC),
        )
        assert profile.risk_zone == "YELLOW"
        assert profile.danger_class_scores["self_harm_avg"] == 0.3


class TestMetricsHistory:
    def test_create(self):
        entry = MetricsHistory(
            end_user_id="user_001",
            temporal_metrics={"daily_message_count": 42},
            danger_class_agg={"self_harm_avg": 0.1},
            behavioral_scores={"topic_concentration": 0.5},
            risk_zone="GREEN",
        )
        assert entry.end_user_id == "user_001"
        assert entry.temporal_metrics["daily_message_count"] == 42


class TestDailySummary:
    def test_create(self):
        summary = DailySummary(
            end_user_id="user_001",
            summary_date=date(2026, 3, 24),
            key_topics=["work stress", "insomnia"],
            life_events=["breakup with partner"],
            emotional_tone="anxious",
            ai_relationship_markers=["called AI 'my friend'"],
            notable_quotes=["\u044f \u0431\u043e\u043b\u044c\u0448\u0435 \u043d\u0435 \u043c\u043e\u0433\u0443"],
            operator_note="Second mention of work problems",
            is_notable=True,
        )
        assert summary.summary_date == date(2026, 3, 24)
        assert summary.is_notable is True
        assert len(summary.key_topics) == 2

    def test_create_unremarkable_day(self):
        summary = DailySummary(
            end_user_id="user_001",
            summary_date=date(2026, 3, 23),
            key_topics=["daily tasks"],
            life_events=[],
            emotional_tone="neutral",
            ai_relationship_markers=[],
            notable_quotes=[],
            is_notable=False,
        )
        assert summary.is_notable is False


class TestBehavioralEvent:
    def test_create_zone_change(self):
        event = BehavioralEvent(
            end_user_id="user_001",
            event_type="risk_zone_change",
            severity="YELLOW",
            details={
                "old_zone": "GREEN",
                "new_zone": "YELLOW",
                "triggered_rules": ["night_messages > 24", "topic_concentration > 0.7"],
            },
        )
        assert event.event_type == "risk_zone_change"
        assert len(event.details["triggered_rules"]) == 2
