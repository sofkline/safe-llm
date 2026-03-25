# Milestone 6: Weekly Report — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement the weekly report generator that assembles per-user reports from MetricsHistory, DailySummary, BehavioralEvents, and UserBehaviorProfile. Reports are generated as text files — no LLM call needed.

**Architecture:** `weekly_report.py` fetches data from the repository (this week vs previous week), computes week-over-week deltas, formats notable days, and assembles the report as a formatted string. The repository needs two new methods for date-range queries. Reports are saved to a configurable output directory.

**Tech Stack:** SQLAlchemy 2.0 (async), Python string formatting, file I/O

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` — Weekly Report (lines 423-464), Milestone 6 (lines 535-543)

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── weekly_report.py         # Replace stub with full implementation
├── repository.py            # Add date-range query methods

ai-safety-dev/tests/
├── test_weekly_report.py    # Report generation tests
```

---

### Task 1: Add repository methods for date-range queries

**Files:**
- Modify: `ai-safety-dev/src/behavioral/repository.py`

The weekly report needs:
- MetricsHistory for a specific date range (this week + previous week)
- Notable DailySummary entries within a date range
- BehavioralEvents within a date range

The existing `get_recent_metrics(days=7)` and `get_recent_events(days=7)` use "last N days from now". We need explicit date-range versions for week-over-week comparison.

- [ ] **Step 1: Add date-range methods to repository**

Append to `ai-safety-dev/src/behavioral/repository.py`:

```python
    # --- Date-range queries for weekly report ---

    async def get_metrics_in_range(
        self, end_user_id: str, start: date, end: date
    ) -> list[MetricsHistory]:
        """Fetch MetricsHistory rows within a date range (inclusive)."""
        async with self._session_factory() as session:
            query = (
                select(MetricsHistory)
                .where(
                    and_(
                        MetricsHistory.end_user_id == end_user_id,
                        MetricsHistory.computed_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                        MetricsHistory.computed_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
                    )
                )
                .order_by(MetricsHistory.computed_at.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_notable_summaries_in_range(
        self, end_user_id: str, start: date, end: date
    ) -> list[DailySummary]:
        """Fetch notable DailySummary rows within a date range."""
        async with self._session_factory() as session:
            query = (
                select(DailySummary)
                .where(
                    and_(
                        DailySummary.end_user_id == end_user_id,
                        DailySummary.is_notable == True,  # noqa: E712
                        DailySummary.summary_date >= start,
                        DailySummary.summary_date <= end,
                    )
                )
                .order_by(DailySummary.summary_date.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    async def get_events_in_range(
        self, end_user_id: str, start: date, end: date
    ) -> list[BehavioralEvent]:
        """Fetch BehavioralEvents within a date range."""
        async with self._session_factory() as session:
            query = (
                select(BehavioralEvent)
                .where(
                    and_(
                        BehavioralEvent.end_user_id == end_user_id,
                        BehavioralEvent.detected_at >= datetime.combine(start, datetime.min.time(), tzinfo=UTC),
                        BehavioralEvent.detected_at < datetime.combine(end + timedelta(days=1), datetime.min.time(), tzinfo=UTC),
                    )
                )
                .order_by(BehavioralEvent.detected_at.asc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())
```

- [ ] **Step 2: Commit**

```bash
git add ai-safety-dev/src/behavioral/repository.py
git commit -m "feat(repository): add date-range query methods for weekly report

get_metrics_in_range, get_notable_summaries_in_range, get_events_in_range."
```

---

### Task 2: Implement weekly report generator

**Files:**
- Replace: `ai-safety-dev/src/behavioral/weekly_report.py`
- Create: `ai-safety-dev/tests/test_weekly_report.py`

- [ ] **Step 1: Create test file**

Create `ai-safety-dev/tests/test_weekly_report.py`:

```python
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
            # this week
            [MagicMock(
                temporal_metrics={"daily_message_count": 40, "night_messages": 8,
                                  "daily_active_hours": 3, "avg_prompt_length_chars": 200},
                danger_class_agg={"self_harm_avg": 0.1, "psychosis_avg": 0.05},
                behavioral_scores={"topic_concentration": 0.5, "social_isolation": 0.3,
                                   "emotional_attachment": 0.4, "decision_delegation": 0.2},
            )],
            # prev week
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
        mock_repo.get_metrics_in_range.return_value = []
        mock_repo.get_notable_summaries_in_range.return_value = []
        mock_repo.get_events_in_range.return_value = []

        with patch("behavioral.weekly_report.BehavioralRepository", return_value=mock_repo):
            report = await generate_weekly_report("user1")

        assert "Weekly Report: user1" in report
        assert "GREEN" in report
        assert "No data" in report
```

- [ ] **Step 2: Replace weekly_report.py**

Replace the entire `ai-safety-dev/src/behavioral/weekly_report.py`:

```python
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

    # Date ranges
    week_end = report_date
    week_start = week_end - timedelta(days=6)
    prev_week_end = week_start - timedelta(days=1)
    prev_week_start = prev_week_end - timedelta(days=6)

    # Fetch data
    profile = await repo.get_profile(end_user_id)
    zone = profile.risk_zone if profile else "GREEN"

    this_week_metrics = await repo.get_metrics_in_range(end_user_id, week_start, week_end)
    prev_week_metrics = await repo.get_metrics_in_range(end_user_id, prev_week_start, prev_week_end)
    notable_days = await repo.get_notable_summaries_in_range(end_user_id, week_start, week_end)
    events = await repo.get_events_in_range(end_user_id, week_start, week_end)

    # Build report
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
```

- [ ] **Step 3: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_weekly_report.py -v
```

- [ ] **Step 4: Run full suite**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/weekly_report.py ai-safety-dev/tests/test_weekly_report.py
git commit -m "feat(weekly_report): implement weekly report generator

Assembles per-user reports from MetricsHistory, DailySummary, BehavioralEvents.
Includes: week-over-week stats comparison, notable days timeline,
behavioral scores, risk zone transitions. No LLM call needed."
```
