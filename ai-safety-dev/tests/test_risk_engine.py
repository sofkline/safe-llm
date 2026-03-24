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
        "self_harm_avg": 0.0,
        "self_harm_max": 0.0,
        "self_harm_flag_rate": 0.0,
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
    async def test_self_harm_flag_rate(self):
        danger = _green_danger()
        danger["self_harm_flag_rate"] = 0.4
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "self_harm_flag_rate > 0.3" in rules

    @pytest.mark.asyncio
    async def test_self_harm_max(self):
        danger = _green_danger()
        danger["self_harm_max"] = 0.85
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), danger, _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "self_harm_max > 0.8" in rules

    @pytest.mark.asyncio
    async def test_daily_active_hours(self):
        temporal = _green_temporal()
        temporal["daily_active_hours"] = 7
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), _green_behavioral(),
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "daily_active_hours > 6" in rules

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
        behavioral = _green_behavioral()
        behavioral["social_isolation"] = 0.7
        behavioral["emotional_attachment"] = 0.6
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), behavioral,
            baselines=_green_baselines(),
        )
        assert zone == "RED"
        assert "social_isolation > 0.6 AND emotional_attachment > 0.5" in rules

    @pytest.mark.asyncio
    async def test_sustained_yellow(self):
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW"})(),
            type("H", (), {"risk_zone": "YELLOW"})(),
            type("H", (), {"risk_zone": "YELLOW"})(),
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
