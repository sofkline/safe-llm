"""Tests for Stage 4: Risk zone engine."""

import pytest
from behavioral.risk_engine import evaluate_risk_zone


def _green_temporal():
    return {
        "daily_message_count": 10,
        "night_messages": 0,
        "daily_active_hours": 1,
        "avg_inter_message_interval_min": 5.0,
    }

def _green_danger():
    return {
        "suicide_avg": 0.0,
        "suicide_max": 0.0,
        "suicide_flag_rate": 0.0,
        "max_class_avg": 0.0,
    }

def _green_behavioral():
    return {
        "topic_concentration": 0.0,
        "decision_delegation": 0.0,
        "social_isolation": 0.0,
        "emotional_attachment": 0.0,
    }

def _green_baselines():
    return {
        "avg_daily_messages": 10,
        "avg_inter_message_interval": 5.0,
    }


class TestGreenZone:
    @pytest.mark.asyncio
    async def test_all_safe_returns_green(self):
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"
        assert rules == []


class TestYellowZone:
    @pytest.mark.asyncio
    async def test_single_trigger_stays_green(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"

    @pytest.mark.asyncio
    async def test_two_triggers_yellow(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
        assert "night_messages > 24" in rules
        assert "topic_concentration > 0.7" in rules

    @pytest.mark.asyncio
    async def test_night_messages_trigger(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 25
        behavioral = _green_behavioral()
        behavioral["decision_delegation"] = 0.5
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
        assert "night_messages > 24" in rules
        assert "decision_delegation > 0.4" in rules

    @pytest.mark.asyncio
    async def test_high_frequency_trending_up(self):
        temporal = _green_temporal()
        temporal["daily_message_count"] = 60
        danger = _green_danger()
        danger["max_class_avg"] = 0.35
        zone, rules = await evaluate_risk_zone(
            temporal, danger, _green_behavioral(),
            baselines={"avg_daily_messages": 20, "avg_inter_message_interval": 5.0},
        )
        assert zone == "YELLOW"
        assert "daily_message_count > 50 AND trending up" in rules
        assert "max_class_avg > 0.3" in rules

    @pytest.mark.asyncio
    async def test_interval_shrinking(self):
        temporal = _green_temporal()
        temporal["avg_inter_message_interval_min"] = 3.0
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines={"avg_daily_messages": 10, "avg_inter_message_interval": 5.0},
        )
        assert zone == "YELLOW"
        assert "interval_shrinking > 30%" in rules


class TestRedZone:
    @pytest.mark.asyncio
    async def test_suicide_flag_rate(self):
        danger = _green_danger()
        danger["suicide_flag_rate"] = 0.4
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "suicide_flag_rate > 0 (any suicide signal — immediate RED)" in rules

    @pytest.mark.asyncio
    async def test_suicide_max(self):
        danger = _green_danger()
        danger["suicide_max"] = 0.85
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "suicide_max > 0.7" in rules

    @pytest.mark.asyncio
    async def test_daily_active_hours(self):
        temporal = _green_temporal()
        temporal["daily_active_hours"] = 8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "daily_active_hours >= 8" in rules

    @pytest.mark.asyncio
    async def test_volume_spike(self):
        temporal = _green_temporal()
        temporal["daily_message_count"] = 250
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "daily_message_count > 200" in rules

    @pytest.mark.asyncio
    async def test_isolation_plus_attachment(self):
        temporal = _green_temporal()
        temporal["daily_message_count"] = 25
        behavioral = _green_behavioral()
        behavioral["social_isolation"] = 0.7
        behavioral["emotional_attachment"] = 0.7
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert ("social_isolation >= 0.7 AND emotional_attachment >= 0.7 "
                "AND daily_messages > 20") in rules

    @pytest.mark.asyncio
    async def test_sustained_yellow(self):
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
        ]
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "RED"
        assert "sustained_yellow >= 3 days" in rules

    @pytest.mark.asyncio
    async def test_red_overrides_yellow(self):
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        temporal["daily_active_hours"] = 7
        behavioral = _green_behavioral()
        behavioral["topic_concentration"] = 0.8
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "RED"


class TestPsychosisFlagRate:
    @pytest.mark.asyncio
    async def test_sustained_psychosis_becomes_yellow_trigger(self):
        """Sustained psychosis_flag_rate > 0.2 for 3 days is a YELLOW trigger."""
        mock_history = [
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.25}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.22}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.21}, "behavioral_scores": {}})(),
        ]
        # Need 2 yellow triggers for YELLOW zone — add night_messages as the second
        temporal = _green_temporal()
        temporal["night_messages"] = 30
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "YELLOW"
        assert "psychosis_flag_rate > 0.2 sustained 3 days" in rules
        assert "night_messages > 24" in rules

    @pytest.mark.asyncio
    async def test_psychosis_not_sustained_no_trigger(self):
        """If psychosis_flag_rate drops below 0.2 in one of the 3 days, no trigger."""
        mock_history = [
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.25}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.15}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.22}, "behavioral_scores": {}})(),
        ]
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "GREEN"
        assert "psychosis_flag_rate > 0.2 sustained 3 days" not in rules

    @pytest.mark.asyncio
    async def test_psychosis_with_less_than_3_days_history(self):
        """Less than 3 days of history: no sustained psychosis check."""
        mock_history = [
            type("H", (), {"risk_zone": "GREEN", "danger_class_agg": {"psychosis_flag_rate": 0.3}, "behavioral_scores": {}})(),
        ]
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "GREEN"
