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


def _format_risk_transitions(events: list) -> str:
    """Build the RISK TRANSITIONS section from BehavioralEvent rows."""
    if not events:
        return "RISK TRANSITIONS:\n  No zone changes this week."

    lines = ["RISK TRANSITIONS:"]
    for e in events:
        details = e.details or {}
        old = details.get("old_zone", "?")
        new = details.get("new_zone", "?")
        triggers = details.get("triggered_rules", [])
        ts = e.detected_at.strftime("%Y-%m-%d") if e.detected_at else "?"
        lines.append(f"  {ts}: {old} → {new}")
        if triggers:
            lines.append(f"    Triggers: {', '.join(triggers)}")
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
    transitions = _format_risk_transitions(events)

    report = f"{header}\n\n{stats}\n\n{notable}\n\n{scores}\n\n{transitions}"

    logger.info("Weekly report generated for %s (%s — %s)", end_user_id, week_start, week_end)
    return report
