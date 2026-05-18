"""Этап 4: Правила определения зоны риска (GREEN/YELLOW/RED).
Любой 1 RED-триггер = RED, любые 2 YELLOW-триггера = YELLOW, иначе GREEN."""

import logging

logger = logging.getLogger(__name__)


async def evaluate_risk_zone(
    temporal_metrics: dict,
    danger_class_agg: dict,
    behavioral_scores: dict,
    baselines: dict | None = None,
    recent_history: list | None = None,
) -> tuple[str, list[str]]:
    """Evaluate risk zone from all stage outputs.

    Args:
        temporal_metrics: Stage 1 output
        danger_class_agg: Stage 2 output
        behavioral_scores: Stage 3 scores
        baselines: 7-day rolling averages for trend detection
        recent_history: last N MetricsHistory rows for sustained-YELLOW check

    Returns:
        (zone, triggered_rules) where zone is GREEN/YELLOW/RED
    """
    if baselines is None:
        baselines = {}
    if recent_history is None:
        recent_history = []

    yellow_triggers = _check_yellow_triggers(temporal_metrics, danger_class_agg, behavioral_scores, baselines)
    red_triggers = _check_red_triggers(temporal_metrics, danger_class_agg, behavioral_scores)

    # Sustained YELLOW check: YELLOW for >=3 consecutive days
    if len(recent_history) >= 3:
        last_3_zones = [h.risk_zone for h in recent_history[:3]]
        if all(z == "YELLOW" for z in last_3_zones):
            red_triggers.append("sustained_yellow >= 3 days")

# ── Sustained signal checks (longitudinal rules)

    # Delusional: flag_rate > 0.2 sustained 3 days → YELLOW
    if len(recent_history) >= 3:
        if all(
            (h.danger_class_agg or {}).get("psychosis_flag_rate", 0) > 0.2
            for h in recent_history[:3]
        ):
            yellow_triggers.append("psychosis_flag_rate > 0.2 sustained 3 days")
   
    # Depression: high topic_concentration + emotional_isolation sustained 3 days → YELLOW
    if len(recent_history) >= 3:
        if all(
            (h.behavioral_scores or {}).get("topic_concentration", 0) > 0.5
            and (h.behavioral_scores or {}).get("emotional_isolation", 0) > 0.4
            for h in recent_history[:3]
        ):
            yellow_triggers.append(
                "topic_concentration > 0.5 AND emotional_isolation > 0.4 sustained 3 days"
            )

    # Selfharm behavioral score rising trend (3 days) → YELLOW (even without RED flag_rate)
    if len(recent_history) >= 3:
        selfharm_trend = [
            (h.behavioral_scores or {}).get("selfharm", 0) for h in recent_history[:3]
        ]
        # Ascending order (most recent first in recent_history)
        if selfharm_trend[0] > selfharm_trend[1] > selfharm_trend[2] and selfharm_trend[0] > 0.3:
            yellow_triggers.append("selfharm score rising trend 3 days")

    # Determine zone: RED (any 1) > YELLOW (any 2) > GREEN
    all_triggers = []
    if red_triggers:
        all_triggers = red_triggers + yellow_triggers
        zone = "RED"
    elif len(yellow_triggers) >= 2:
        all_triggers = yellow_triggers
        zone = "YELLOW"
    else:
        zone = "GREEN"

    if all_triggers:
        logger.info("Risk zone %s for triggers: %s", zone, all_triggers)

    return zone, all_triggers


def _check_yellow_triggers(
    temporal: dict, danger: dict, behavioral: dict, baselines: dict
) -> list[str]:
    """Check all YELLOW trigger rules. Returns list of triggered rule names."""
    triggers = []

    if temporal.get("night_messages", 0) > 24:
        triggers.append("night_messages > 24")

    daily_msgs = temporal.get("daily_message_count", 0)
    baseline_msgs = baselines.get("avg_daily_messages", 0)
    if daily_msgs > 50 and baseline_msgs > 0 and daily_msgs > baseline_msgs * 1.5:
        triggers.append("daily_message_count > 50 AND trending up")

    if danger.get("max_class_avg", 0) > 0.3:
        triggers.append("max_class_avg > 0.3")

    if behavioral.get("topic_concentration", 0) > 0.7:
        triggers.append("topic_concentration > 0.7")

    if behavioral.get("decision_delegation", 0) > 0.4:
        triggers.append("decision_delegation > 0.4")

    if behavioral.get("emotional_attachment", 0) > 0.5:
        triggers.append("emotional_attachment > 0.5")

    if behavioral.get("social_isolation", 0) > 0.4 and behavioral.get("emotional_attachment", 0) > 0.4:
        triggers.append("social_isolation > 0.4 AND emotional_attachment > 0.4")

    if temporal.get("daily_active_hours", 0) >= 6:
        triggers.append("daily_active_hours >= 6")

    baseline_interval = baselines.get("avg_inter_message_interval", 0)
    current_interval = temporal.get("avg_inter_message_interval_min", 0)
    if baseline_interval > 0 and current_interval > 0:
        decrease = (baseline_interval - current_interval) / baseline_interval
        if decrease > 0.3:
            triggers.append("interval_shrinking > 30%")

    # Rumination (topic_concentration) + emotional isolation together
    if (
        behavioral.get("topic_concentration", 0) > 0.6
        and behavioral.get("emotional_isolation", 0) > 0.5
    ):
        triggers.append("topic_concentration > 0.6 AND emotional_isolation > 0.5 (depression pattern)")

    # Emotional isolation alone at moderate level: loneliness as AI-substitute
    if behavioral.get("emotional_isolation", 0) > 0.6:
        triggers.append("emotional_isolation > 0.6")

    # Depression class flag rate (Stage 2 classifier)
    if danger.get("depression_flag_rate", 0) > 0.3:
        triggers.append("depression_flag_rate > 0.3")

    # Moderate delusional score: single-day signal → YELLOW
    if behavioral.get("delusional", 0) > 0.5:
        triggers.append("delusional > 0.5")

    # Moderate selfharm score without explicit method-seeking → YELLOW
    if behavioral.get("selfharm", 0) > 0.4:
        triggers.append("selfharm > 0.4")

    # Suicide flag present in any session today → YELLOW immediately
    # (even a single flag warrants elevated attention — asymmetric cost of miss)
    if danger.get("suicide_flag_rate", 0) > 0.0:
        triggers.append("suicide_flag_rate > 0 (any suicide signal today)")

    return triggers


def _check_red_triggers(
    temporal: dict, danger: dict, behavioral: dict
) -> list[str]:
    """Check all RED trigger rules. Returns list of triggered rule names."""
    triggers = []

    active_hours = temporal.get("daily_active_hours", 0)
    if active_hours >= 8:
        triggers.append("daily_active_hours >= 8")
    elif active_hours >= 6 and (
        behavioral.get("emotional_attachment", 0) > 0.3
        or behavioral.get("topic_concentration", 0) > 0.5
    ):
        triggers.append("daily_active_hours >= 6 AND (attachment > 0.3 OR concentration > 0.5)")

    if temporal.get("daily_message_count", 0) > 200:
        triggers.append("daily_message_count > 200")

    iso = behavioral.get("social_isolation", 0)
    attach = behavioral.get("emotional_attachment", 0)
    daily_msgs = temporal.get("daily_message_count", 0)
    if iso >= 0.7 and attach >= 0.7 and daily_msgs > 20:
        triggers.append("social_isolation >= 0.7 AND emotional_attachment >= 0.7 AND daily_messages > 20")
    
    # High depression flag rate from Stage 2 classifier
    if danger.get("depression_flag_rate", 0) > 0.6:
        triggers.append("depression_flag_rate > 0.6")

    # Extreme emotional isolation + high topic concentration: severe depression signal
    # User is completely isolated and ruminating — requires intervention
    if (
        behavioral.get("emotional_isolation", 0) >= 0.7
        and behavioral.get("topic_concentration", 0) >= 0.7
    ):
        triggers.append("emotional_isolation >= 0.7 AND topic_concentration >= 0.7 (severe depression signal)")

    # High delusional score: AI is reinforcing delusions (Chopra et al., 2026)
    if behavioral.get("delusional", 0) >= 0.7:
        triggers.append("delusional >= 0.7")

    # Psychosis class flag rate high: repeatedly triggered across sessions
    if danger.get("psychosis_flag_rate", 0) > 0.5:
        triggers.append("psychosis_flag_rate > 0.5")

    # High-confidence single psychosis/delusional message → RED immediately
    if danger.get("psychosis_max", 0) > 0.8:
        triggers.append("psychosis_max > 0.8")

    # High selfharm behavioral score: user expressing current urges or method-seeking
    # Regression analysis: selfharm frequency raises suicide attempt probability by 58.8%
    if behavioral.get("selfharm", 0) >= 0.7:
        triggers.append("selfharm >= 0.7")

    # Any suicide class flag from Stage 2 → RED immediately.
    # Asymmetric risk: missing a crisis is incomparably worse than a false alarm.
    if danger.get("suicide_flag_rate", 0) > 0.0:
        triggers.append("suicide_flag_rate > 0 (any suicide signal — immediate RED)")

    # High confidence single-message suicide signal (max confidence)
    if danger.get("suicide_max", 0) > 0.7:
        triggers.append("suicide_max > 0.7")

    # Selfharm score high + night activity: nocturnal crisis amplifier
    if behavioral.get("selfharm", 0) > 0.5 and temporal.get("night_messages", 0) > 5:
        triggers.append("selfharm > 0.5 AND night_messages > 5 (nocturnal crisis signal)")

    return triggers
