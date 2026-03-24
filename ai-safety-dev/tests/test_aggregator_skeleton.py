"""Tests for the aggregator pipeline orchestrator (skeleton stage)."""

import pytest
import pytest_asyncio
from unittest.mock import AsyncMock, patch
from datetime import datetime, UTC

from behavioral.aggregator import run_aggregator_for_user, _compute_is_notable


class TestComputeIsNotable:
    """Test the is_notable filtering logic."""

    def test_notable_when_life_events(self):
        summary = {
            "life_events": ["breakup"],
            "ai_relationship_markers": [],
            "emotional_tone": "neutral",
        }
        assert _compute_is_notable(summary, {}) is True

    def test_notable_when_ai_markers(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": ["called AI by name"],
            "emotional_tone": "neutral",
        }
        assert _compute_is_notable(summary, {}) is True

    def test_notable_when_emotional_tone(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "anxious, distressed",
        }
        assert _compute_is_notable(summary, {}) is True

    def test_not_notable_when_neutral(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "neutral",
        }
        assert _compute_is_notable(summary, {}) is False

    def test_not_notable_when_calm(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "calm",
        }
        assert _compute_is_notable(summary, {}) is False

    def test_notable_when_topic_concentration_high(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "neutral",
        }
        scores = {"topic_concentration": 0.8}
        assert _compute_is_notable(summary, scores) is True

    def test_notable_when_decision_delegation_high(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "neutral",
        }
        scores = {"decision_delegation": 0.5}
        assert _compute_is_notable(summary, scores) is True

    def test_not_notable_when_scores_below_threshold(self):
        summary = {
            "life_events": [],
            "ai_relationship_markers": [],
            "emotional_tone": "normal",
        }
        scores = {"topic_concentration": 0.5, "decision_delegation": 0.3}
        assert _compute_is_notable(summary, scores) is False


class TestAggregatorPipeline:
    """Test that the pipeline orchestrator calls all stages and writes results."""

    @pytest.mark.asyncio
    async def test_pipeline_runs_all_stages(self):
        """Verify all 4 stages execute and post-write steps complete."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_metrics.return_value = []
        mock_repo.get_profile.return_value = None  # new user

        with (
            patch("behavioral.aggregator.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.aggregator.compute_temporal_metrics") as mock_s1,
            patch("behavioral.aggregator.compute_danger_class_agg") as mock_s2,
            patch("behavioral.aggregator.compute_behavioral_scores_and_summary") as mock_s3,
            patch("behavioral.aggregator.evaluate_risk_zone") as mock_s4,
        ):
            mock_s1.return_value = {"daily_message_count": 0}
            mock_s2.return_value = {"self_harm_avg": 0.0}
            mock_s3.return_value = {
                "scores": {"topic_concentration": 0.0},
                "summary": {
                    "key_topics": [],
                    "life_events": [],
                    "emotional_tone": "neutral",
                    "ai_relationship_markers": [],
                    "notable_quotes": [],
                    "operator_note": None,
                },
            }
            mock_s4.return_value = ("GREEN", [])

            await run_aggregator_for_user("test_user")

            mock_s1.assert_awaited_once_with("test_user")
            mock_s2.assert_awaited_once_with("test_user")
            mock_s3.assert_awaited_once()
            mock_s4.assert_awaited_once()
            mock_repo.add_metrics_history.assert_awaited_once()
            mock_repo.add_daily_summary.assert_awaited_once()
            mock_repo.upsert_profile.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_emits_event_on_zone_change(self):
        """Verify BehavioralEvent is written when zone changes."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_metrics.return_value = []
        mock_profile = AsyncMock()
        mock_profile.risk_zone = "GREEN"
        mock_repo.get_profile.return_value = mock_profile

        with (
            patch("behavioral.aggregator.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.aggregator.compute_temporal_metrics", return_value={}),
            patch("behavioral.aggregator.compute_danger_class_agg", return_value={}),
            patch("behavioral.aggregator.compute_behavioral_scores_and_summary", return_value={
                "scores": {},
                "summary": {
                    "key_topics": [], "life_events": [], "emotional_tone": "neutral",
                    "ai_relationship_markers": [], "notable_quotes": [], "operator_note": None,
                },
            }),
            patch("behavioral.aggregator.evaluate_risk_zone", return_value=("YELLOW", ["night_messages > 24"])),
        ):
            await run_aggregator_for_user("test_user")
            mock_repo.add_event.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_pipeline_no_event_when_zone_unchanged(self):
        """Verify no BehavioralEvent when zone stays the same."""
        mock_repo = AsyncMock()
        mock_repo.get_recent_metrics.return_value = []
        mock_profile = AsyncMock()
        mock_profile.risk_zone = "GREEN"
        mock_repo.get_profile.return_value = mock_profile

        with (
            patch("behavioral.aggregator.BehavioralRepository", return_value=mock_repo),
            patch("behavioral.aggregator.compute_temporal_metrics", return_value={}),
            patch("behavioral.aggregator.compute_danger_class_agg", return_value={}),
            patch("behavioral.aggregator.compute_behavioral_scores_and_summary", return_value={
                "scores": {},
                "summary": {
                    "key_topics": [], "life_events": [], "emotional_tone": "neutral",
                    "ai_relationship_markers": [], "notable_quotes": [], "operator_note": None,
                },
            }),
            patch("behavioral.aggregator.evaluate_risk_zone", return_value=("GREEN", [])),
        ):
            await run_aggregator_for_user("test_user")
            mock_repo.add_event.assert_not_awaited()
