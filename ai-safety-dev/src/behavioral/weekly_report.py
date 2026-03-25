"""Weekly report generator — assembles per-user reports from DB data."""

import logging
from datetime import date, datetime, timedelta, UTC

from behavioral.repository import BehavioralRepository

logger = logging.getLogger(__name__)


def _format_change(current: float, previous: float) -> str:
    """Format a week-over-week percentage change."""
    if previous == 0:
        return "new" if current > 0 else "0%"
    pct = round((current - previous) / previous * 100)
    if pct > 0:
        return f"+{pct}%"
    return f"{pct}%"


def _avg_metric(rows, path_fn) -> float:
    """Compute average of a metric across MetricsHistory rows."""
    values = []
    for r in rows:
        val = path_fn(r)
        if val is not None:
            values.append(val)
    return sum(values) / len(values) if values else 0.0


def _compute_stats_section(this_week: list, prev_week: list) -> str:
    """Build the STATS section comparing this week vs previous week."""
    def _tm(row, key):
        return (row.temporal_metrics or {}).get(key, 0)
    def _dc(row, key):
        return (row.danger_class_agg or {}).get(key, 0)

    tw_msgs = _avg_metric(this_week, lambda r: _tm(r, "daily_message_count"))
    pw_msgs = _avg_metric(prev_week, lambda r: _tm(r, "daily_message_count"))

    tw_night = _avg_metric(this_week, lambda r: _tm(r, "night_messages"))
    pw_night = _avg_metric(prev_week, lambda r: _tm(r, "night_messages"))

    tw_hours = _avg_metric(this_week, lambda r: _tm(r, "daily_active_hours"))
    pw_hours = _avg_metric(prev_week, lambda r: _tm(r, "daily_active_hours"))

    tw_len = _avg_metric(this_week, lambda r: _tm(r, "avg_prompt_length_chars"))
    pw_len = _avg_metric(prev_week, lambda r: _tm(r, "avg_prompt_length_chars"))

    tw_sh = _avg_metric(this_week, lambda r: _dc(r, "self_harm_avg"))
    pw_sh = _avg_metric(prev_week, lambda r: _dc(r, "self_harm_avg"))

    tw_ps = _avg_metric(this_week, lambda r: _dc(r, "psychosis_avg"))
    pw_ps = _avg_metric(prev_week, lambda r: _dc(r, "psychosis_avg"))

    lines = [
        "STATS (this week / previous week):",
        f"  Messages:        {tw_msgs:.0f} / {pw_msgs:.0f}      ({_format_change(tw_msgs, pw_msgs)})",
        f"  Night messages:  {tw_night:.0f} / {pw_night:.0f}      ({_format_change(tw_night, pw_night)})",
        f"  Active hours:    {tw_hours:.1f} / {pw_hours:.1f}      ({_format_change(tw_hours, pw_hours)})",
        f"  Avg msg length:  {tw_len:.0f}ch / {pw_len:.0f}ch  ({_format_change(tw_len, pw_len)})",
        f"  Self-harm avg:   {tw_sh:.2f} / {pw_sh:.2f}",
        f"  Psychosis avg:   {tw_ps:.2f} / {pw_ps:.2f}",
    ]
    return "\n".join(lines)


def _format_notable_days_section(summaries: list) -> str:
    """Build the NOTABLE DAYS section from DailySummary rows."""
    if not summaries:
        return "NOTABLE DAYS:\n  No notable days this week."

    lines = ["NOTABLE DAYS:"]
    for s in summaries:
        topics = ", ".join(s.key_topics) if s.key_topics else "none"
        events = ", ".join(s.life_events) if s.life_events else "none"
        markers = ", ".join(s.ai_relationship_markers) if s.ai_relationship_markers else "none"
        lines.append(f"  {s.summary_date} — {topics}")
        lines.append(f"           Events: {events}")
        lines.append(f"           Tone: {s.emotional_tone or 'neutral'}")
        lines.append(f"           Markers: {markers}")
        if s.notable_quotes:
            for q in s.notable_quotes[:2]:
                lines.append(f'           "{q}"')
        if s.operator_note:
            lines.append(f"           ⚠ {s.operator_note}")
    return "\n".join(lines)


def _format_behavioral_scores(metrics_rows: list) -> str:
    """Build the BEHAVIORAL SCORES section from the latest MetricsHistory row."""
    if not metrics_rows:
        return "BEHAVIORAL SCORES (latest):\n  No data available."
    latest = metrics_rows[-1]
    scores = latest.behavioral_scores or {}
    tc = scores.get("topic_concentration", 0)
    si = scores.get("social_isolation", 0)
    ea = scores.get("emotional_attachment", 0)
    dd = scores.get("decision_delegation", 0)
    return (
        "BEHAVIORAL SCORES (latest):\n"
        f"  Topic concentration: {tc:.2f} | Isolation: {si:.2f} | "
        f"Attachment: {ea:.2f} | Delegation: {dd:.2f}"
    )


def _explain_trigger(trigger: str, context: dict) -> str:
    """Convert a raw trigger rule into a human-readable explanation."""
    temporal = context.get("temporal_metrics", {})
    danger = context.get("danger_class_agg", {})
    behavioral = context.get("behavioral_scores", {})
    baselines = context.get("baselines", {})

    explanations = {
        "night_messages > 24": lambda: (
            f"User sent {temporal.get('night_messages', '?')} messages between 22:00-03:00 "
            f"(baseline: {baselines.get('avg_night_messages', 0):.0f})"
        ),
        "daily_message_count > 50 AND trending up": lambda: (
            f"User sent {temporal.get('daily_message_count', '?')} messages today, "
            f"{baselines.get('avg_daily_messages', 0):.0f}/day avg last week"
        ),
        "max_class_avg > 0.3": lambda: (
            f"Danger classifier signal elevated: avg {danger.get('max_class_avg', 0):.2f} (threshold: 0.3)"
        ),
        "topic_concentration > 0.7": lambda: (
            f"Conversation focused on a single topic: score {behavioral.get('topic_concentration', 0):.2f}/1.0"
        ),
        "decision_delegation > 0.4": lambda: (
            f"User frequently asked AI to make decisions: score {behavioral.get('decision_delegation', 0):.2f}/1.0"
        ),
        "interval_shrinking > 30%": lambda: (
            f"Time between messages shrinking: "
            f"{temporal.get('avg_inter_message_interval_min', 0):.1f} min vs "
            f"{baselines.get('avg_inter_message_interval', 0):.1f} min baseline"
        ),
        "self_harm_flag_rate > 0.3": lambda: (
            f"Self-harm signals in {danger.get('self_harm_flag_rate', 0)*100:.0f}% of messages"
        ),
        "self_harm_max > 0.8": lambda: (
            f"High-confidence self-harm signal: max {danger.get('self_harm_max', 0):.2f}"
        ),
        "daily_active_hours > 6": lambda: (
            f"User active for {temporal.get('daily_active_hours', '?')} hours today"
        ),
        "daily_message_count > 200": lambda: (
            f"Extreme message volume: {temporal.get('daily_message_count', '?')} messages in 24h"
        ),
        "sustained_yellow >= 3 days": lambda: "User in YELLOW zone for 3+ consecutive days",
        "social_isolation > 0.6 AND emotional_attachment > 0.5": lambda: (
            f"Social isolation ({behavioral.get('social_isolation', 0):.2f}) "
            f"+ AI attachment ({behavioral.get('emotional_attachment', 0):.2f})"
        ),
        "delusion_flag_rate > 0.2 sustained 3 days": lambda: (
            f"Delusional content flagged 3+ consecutive days "
            f"(rate: {danger.get('delusion_flag_rate', 0):.2f})"
        ),
    }

    fn = explanations.get(trigger)
    if fn:
        try:
            return fn()
        except Exception:
            return trigger
    return trigger


def _format_risk_transitions(events: list, metrics_rows: list = None) -> str:
    """Build the RISK TRANSITIONS section with human-readable explanations."""
    if not events:
        return "RISK TRANSITIONS:\n  No zone changes this week."

    # Build date->metrics lookup for trigger explanations
    metrics_by_date = {}
    if metrics_rows:
        for r in metrics_rows:
            d = r.computed_at.date() if r.computed_at else None
            if d:
                metrics_by_date[d] = {
                    "temporal_metrics": r.temporal_metrics or {},
                    "danger_class_agg": r.danger_class_agg or {},
                    "behavioral_scores": r.behavioral_scores or {},
                    "baselines": {},
                }

    lines = ["RISK TRANSITIONS:"]
    for e in events:
        details = e.details or {}
        old = details.get("old_zone", "?")
        new = details.get("new_zone", "?")
        triggers = details.get("triggered_rules", [])
        ts = e.detected_at.strftime("%Y-%m-%d") if e.detected_at else "?"
        lines.append(f"  {ts}: {old} → {new}")

        event_date = e.detected_at.date() if e.detected_at else None
        context = metrics_by_date.get(event_date, {})
        for t in triggers:
            explanation = _explain_trigger(t, context)
            lines.append(f"    — {explanation}")
    return "\n".join(lines)


async def generate_weekly_report(
    end_user_id: str,
    report_date: date | None = None,
) -> str:
    """Generate a weekly report for a user.

    Args:
        end_user_id: the user to report on
        report_date: the end date of the report week (defaults to today UTC)

    Returns:
        Formatted report string.
    """
    if report_date is None:
        report_date = datetime.now(UTC).date()

    repo = BehavioralRepository()

    week_end = report_date
    week_start = week_end - timedelta(days=6)
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)

    profile = await repo.get_profile(end_user_id)
    zone = profile.risk_zone if profile else "GREEN"

    this_week_metrics = await repo.get_metrics_in_range(end_user_id, week_start, week_end)
    prev_week_metrics = await repo.get_metrics_in_range(end_user_id, prev_week_start, prev_week_end)
    notable_days = await repo.get_notable_summaries_in_range(end_user_id, week_start, week_end)
    events = await repo.get_events_in_range(end_user_id, week_start, week_end)

    header = f"=== Weekly Report: {end_user_id} | {week_start} — {week_end} | {zone} ==="

    if not this_week_metrics:
        return f"{header}\n\nNo data for this week."

    stats = _compute_stats_section(this_week_metrics, prev_week_metrics)
    notable = _format_notable_days_section(notable_days)
    scores = _format_behavioral_scores(this_week_metrics)
    transitions = _format_risk_transitions(events, this_week_metrics)

    report = f"{header}\n\n{stats}\n\n{notable}\n\n{scores}\n\n{transitions}"

    logger.info("Weekly report generated for %s (%s — %s)", end_user_id, week_start, week_end)
    return report
