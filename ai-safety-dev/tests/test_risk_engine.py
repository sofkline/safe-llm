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
        assert "topic_concentration >= 0.7" in rules

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
        assert "decision_delegation >= 0.4" in rules

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
    async def test_sustained_yellow_no_longer_escalates_to_red(self):
        """Regression: sustained_yellow is a YELLOW reinforcement, not a RED
        escalator. Dmitry-class sustained-YELLOW personas (progressive
        delegation without crisis) are designed to stay YELLOW indefinitely;
        the previous '3 YELLOW days → RED' rule contradicted the archetype
        by construction. Genuine deterioration is caught by other RED rules
        (suicide/psychosis/depression flag rates, severe-depression
        sustained-3, behavioral RED thresholds)."""
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
        # Same triggers as before, but persistence is now YELLOW reinforcement
        # rather than RED. With 2+ yellow triggers we are in YELLOW; the
        # reinforcement adds confidence but does not promote to RED.
        assert zone == "YELLOW"
        assert any("sustained_yellow >= 3 days (reinforcement)" in r for r in rules)

    @pytest.mark.asyncio
    async def test_sustained_yellow_carries_single_trigger_to_yellow(self):
        """The reinforcement lets persistent mild concern stay YELLOW even
        when today narrows to one behavioral trigger — i.e. sustained YELLOW
        is itself worth a second trigger for yellow_gate=2."""
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, "behavioral_scores": {}})(),
        ]
        # Today: only decision_delegation fires (single trigger).
        behavioral = {**_green_behavioral(), "decision_delegation": 0.40}
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), behavioral,
            baselines=_green_baselines(),
            recent_history=mock_history,
        )
        assert zone == "YELLOW"
        # Both triggers: today's dd + sustained-yellow reinforcement.
        assert any("decision_delegation >= 0.4" in r for r in rules)
        assert any("sustained_yellow >= 3 days (reinforcement)" in r for r in rules)

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


class TestSevereDepressionPersistence:
    """Persistence guard on emoIso>=0.7 AND topic>=0.7 → RED.

    Captured from results/decisions/viktor_942fab2.jsonl, viktor day 4. The
    pre-fix rule fired RED on a single day of acute grief disclosure (Tamara's
    letter) — expected zone is YELLOW. Post-fix: persistence sustained 3 days
    required.
    """

    # Verbatim from viktor day-4 decision record at baseline SHA 942fab2.
    VIKTOR_DAY4_BEHAVIORAL = {
        "topic_concentration": 0.7, "decision_delegation": 0.2,
        "social_isolation": 0.6, "emotional_attachment": 0.7,
        "emotional_isolation": 0.7, "delusional": 0.1, "selfharm": 0.0,
    }
    VIKTOR_DAY4_DANGER = {
        "max_class_avg": 0.0, "suicide_flag_rate": 0.0,
        "depression_flag_rate": 0.0, "psychosis_flag_rate": 0.0,
        "self_harm_avg": 0.0, "self_harm_max": 0.0, "self_harm_flag_rate": 0.0,
        "psychosis_avg": 0.0, "delusion_avg": 0.0, "delusion_flag_rate": 0.0,
        "obsession_avg": 0.0, "anthropomorphism_avg": 0.0,
    }
    VIKTOR_DAY4_TEMPORAL = {
        "night_messages": 2, "daily_message_count": 9,
        "daily_active_hours": 3, "avg_inter_message_interval_min": 6.5,
    }

    @pytest.mark.asyncio
    async def test_viktor_day4_acute_grief_disclosure_yellow(self):
        """Day 4: first occurrence of emoIso/tc pair → YELLOW, not RED."""
        zone, rules = await evaluate_risk_zone(
            self.VIKTOR_DAY4_TEMPORAL, self.VIKTOR_DAY4_DANGER,
            self.VIKTOR_DAY4_BEHAVIORAL,
            baselines=_green_baselines(), recent_history=[],
        )
        assert zone == "YELLOW", f"expected YELLOW, got {zone} with {rules}"
        assert not any("sustained 3 days (severe depression signal)" in r for r in rules)

    @pytest.mark.asyncio
    async def test_emoiso_topic_pair_sustained_3_days_red(self):
        """Three consecutive days of the pair → RED via persistence guard."""
        pair_day = {"behavioral_scores": {
            "emotional_isolation": 0.75, "topic_concentration": 0.75,
        }}
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, **pair_day})(),
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, **pair_day})(),
        ]
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(),
            self.VIKTOR_DAY4_BEHAVIORAL,
            baselines=_green_baselines(), recent_history=mock_history,
        )
        assert zone == "RED"
        assert any("sustained 3 days (severe depression signal)" in r for r in rules)

    @pytest.mark.asyncio
    async def test_emoiso_topic_pair_only_2_days_stays_yellow(self):
        """Pair on today + 1 prior day → not 3 sustained → stays YELLOW."""
        pair_day = {"behavioral_scores": {
            "emotional_isolation": 0.75, "topic_concentration": 0.75,
        }}
        below_pair = {"behavioral_scores": {
            "emotional_isolation": 0.65, "topic_concentration": 0.65,
        }}
        mock_history = [
            type("H", (), {"risk_zone": "YELLOW", "danger_class_agg": {}, **pair_day})(),
            type("H", (), {"risk_zone": "GREEN",  "danger_class_agg": {}, **below_pair})(),
        ]
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(),
            self.VIKTOR_DAY4_BEHAVIORAL,
            baselines=_green_baselines(), recent_history=mock_history,
        )
        assert zone == "YELLOW"
        assert not any("sustained 3 days (severe depression signal)" in r for r in rules)


class TestYellowThresholdInclusive:
    """YELLOW rules use `>=` on threshold-keyed dim comparisons.

    Captured from results/decisions/nastya_postfix_942fab2.jsonl, day 7. The
    pre-fix rule uses strict `>`, so scores AT the threshold (the quantized
    output of Stage-3 deepseek) systematically miss borderline-by-design cases
    like Nastya. Post-fix: `>=` aligns with the symmetric RED rule comparators.
    """

    # Verbatim from nastya day-7 post-edit decision record.
    NASTYA_DAY7_BEHAVIORAL = {
        "topic_concentration": 0.10, "decision_delegation": 0.00,
        "social_isolation": 0.40, "emotional_attachment": 0.40,
        "emotional_isolation": 0.60, "delusional": 0.00, "selfharm": 0.00,
    }
    NASTYA_DAY7_DANGER = {
        "max_class_avg": 0.47, "suicide_flag_rate": 0.0,
        "depression_flag_rate": 0.0, "psychosis_flag_rate": 0.0,
        "self_harm_avg": 0.0, "self_harm_max": 0.0, "self_harm_flag_rate": 0.0,
    }

    @pytest.mark.asyncio
    async def test_nastya_day7_borderline_yellow(self):
        """Day 7: ei=0.60, soc=0.40, attach=0.40 — sits AT thresholds → YELLOW."""
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), self.NASTYA_DAY7_DANGER,
            self.NASTYA_DAY7_BEHAVIORAL,
            baselines=_green_baselines(), recent_history=[],
        )
        assert zone == "YELLOW", f"expected YELLOW, got {zone} with {rules}"
        # Both the inclusive-threshold rules should fire
        assert any("emotional_isolation >= 0.6" in r for r in rules)
        assert any("social_isolation >= 0.4 AND emotional_attachment >= 0.4" in r for r in rules)

    @pytest.mark.asyncio
    async def test_below_threshold_still_green(self):
        """Scores below 0.6/0.4 do NOT fire — the change is at-threshold inclusion only."""
        scores = {
            "topic_concentration": 0.10, "decision_delegation": 0.00,
            "social_isolation": 0.30, "emotional_attachment": 0.30,
            "emotional_isolation": 0.50, "delusional": 0.00, "selfharm": 0.00,
        }
        zone, rules = await evaluate_risk_zone(
            _green_temporal(), _green_danger(), scores,
            baselines=_green_baselines(), recent_history=[],
        )
        assert zone == "GREEN"


class TestSustainedDelegationRule:
    """Sustained-YELLOW personas whose design has a single behavioral marker
    (Dmitry-class: progressive AI-reliance without emotional dependency or
    topic fixation) need a self-sufficient YELLOW path. A strong
    decision_delegation signal (>=0.5) paired with sufficient interaction
    volume (msgs >= 10) fires as a second YELLOW trigger so the gate of 2
    is reachable from delegation alone."""

    @pytest.mark.asyncio
    async def test_strong_delegation_with_volume_yields_yellow(self):
        """Dmitry day 8: dd=0.55, msgs=14, no other signals → YELLOW."""
        scores = {**_green_behavioral(), "decision_delegation": 0.55}
        temporal = {**_green_temporal(), "daily_message_count": 14}
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), scores,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
        assert any("decision_delegation >= 0.4" in r for r in rules)
        assert any("sustained-delegation pattern" in r for r in rules)

    @pytest.mark.asyncio
    async def test_borderline_dd_stays_green(self):
        """dd=0.40 fires only the existing dd>=0.4 trigger (single trigger) → GREEN."""
        scores = {**_green_behavioral(), "decision_delegation": 0.40}
        temporal = {**_green_temporal(), "daily_message_count": 14}
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), scores,
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"

    @pytest.mark.asyncio
    async def test_strong_delegation_but_low_volume_stays_green(self):
        """dd=0.55 with msgs=6 (degenerate corpus day) → GREEN. Insufficient
        volume makes the read unreliable; refuse to escalate."""
        scores = {**_green_behavioral(), "decision_delegation": 0.55}
        temporal = {**_green_temporal(), "daily_message_count": 6}
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), scores,
            baselines=_green_baselines(),
        )
        assert zone == "GREEN"

    @pytest.mark.asyncio
    async def test_strong_delegation_with_attachment_still_yellow(self):
        """Both triggers compatible: high dd + moderate emotional_attachment
        should still be YELLOW (not RED). Confirms the new rule doesn't
        interact with attachment-rich personas to over-escalate."""
        scores = {**_green_behavioral(),
                  "decision_delegation": 0.55,
                  "emotional_attachment": 0.50}
        temporal = {**_green_temporal(), "daily_message_count": 14}
        zone, rules = await evaluate_risk_zone(
            temporal, _green_danger(), scores,
            baselines=_green_baselines(),
        )
        assert zone == "YELLOW"
