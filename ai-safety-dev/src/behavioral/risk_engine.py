"""Stage 4: Rule-based risk zone engine."""

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

    baseline_interval = baselines.get("avg_inter_message_interval", 0)
    current_interval = temporal.get("avg_inter_message_interval_min", 0)
    if baseline_interval > 0 and current_interval > 0:
        decrease = (baseline_interval - current_interval) / baseline_interval
        if decrease > 0.3:
            triggers.append("interval_shrinking > 30%")

    return triggers


def _check_red_triggers(
    temporal: dict, danger: dict, behavioral: dict
) -> list[str]:
    """Check all RED trigger rules. Returns list of triggered rule names."""
    triggers = []

    if danger.get("self_harm_flag_rate", 0) > 0.3:
        triggers.append("self_harm_flag_rate > 0.3")
    if danger.get("self_harm_max", 0) > 0.8:
        triggers.append("self_harm_max > 0.8")

    if temporal.get("daily_active_hours", 0) > 6:
        triggers.append("daily_active_hours > 6")

    if temporal.get("daily_message_count", 0) > 200:
        triggers.append("daily_message_count > 200")

    if behavioral.get("social_isolation", 0) > 0.6 and behavioral.get("emotional_attachment", 0) > 0.5:
        triggers.append("social_isolation > 0.6 AND emotional_attachment > 0.5")

    return triggers
