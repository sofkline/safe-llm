# Milestone 2: Temporal Metrics — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement Stage 1 of the aggregator pipeline — compute all 7 temporal metrics from SpendLogs for each user's last 24h window, plus 7-day rolling baselines and trend flags.

**Architecture:** `temporal.py` queries `LiteLLM_SpendLogs` via async SQLAlchemy, extracts user messages from the cumulative `messages` JSON, and computes metrics in Python. The 7-day baseline comes from the last 7 `MetricsHistory` rows. No changes to the aggregator orchestrator — just replacing the stub with real logic.

**Tech Stack:** SQLAlchemy 2.0 (async), Python datetime, JSON parsing

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md` — Stage 1 metrics reference (lines 97-111) and pipeline steps (lines 288-306)

---

## Critical Domain Knowledge

### SpendLogs `messages` field is CUMULATIVE

Each SpendLogs row contains the **full conversation history** at the time of the request. The `messages` field is a JSON array like:

```json
[
    {"role": "user", "content": "First message"},
    {"role": "assistant", "content": "First response"},
    {"role": "user", "content": "Current message"}
]
```

To get the **current user message** for a given row, extract the **last element with `role == "user"`** from the array. Do NOT count all user messages in the array — that would count the same message multiple times across rows.

### SpendLogs key columns

- `end_user` (String, nullable) — user identifier, may be NULL
- `startTime` (DateTime, NOT NULL, indexed) — when the request was made
- `messages` (JSON, nullable) — cumulative conversation array
- `request_id` (String, PK)

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── temporal.py              # Replace stub with full Stage 1 implementation

ai-safety-dev/tests/
├── test_temporal_metrics.py # Unit tests for all 7 metrics + baselines + trends
```

---

## Metrics Summary

| # | Metric | Field | Computation |
|---|--------|-------|-------------|
| 1 | Daily message count | `daily_message_count` | COUNT of SpendLogs rows for user in last 24h |
| 2 | Hourly distribution | `activity_by_hour` | `{0: N, ..., 23: N}` histogram by UTC hour |
| 3 | Night messages | `night_messages` | COUNT where hour in [22, 23, 0, 1, 2, 3] |
| 4 | Active hours | `daily_active_hours` | COUNT of distinct UTC hours with ≥1 message |
| 5 | Avg prompt length | `avg_prompt_length_chars` | AVG(len(last_user_message)) |
| 6 | Inter-message interval | `avg_inter_message_interval_min` | AVG of time gaps between consecutive startTimes |
| 7 | Messages last 1h | `messages_last_1h` | COUNT in last 60 minutes |

---

### Task 1: Extract user messages from SpendLogs

**Files:**
- Modify: `ai-safety-dev/src/behavioral/temporal.py`
- Create: `ai-safety-dev/tests/test_temporal_metrics.py`

The foundation: fetch SpendLogs rows and extract the last user message from each cumulative messages array.

- [ ] **Step 1: Write test for message extraction helper**

In `ai-safety-dev/tests/test_temporal_metrics.py`:

```python
"""Tests for Stage 1: Temporal metrics computation."""

import pytest
from datetime import datetime, timedelta, UTC

from behavioral.temporal import _extract_last_user_message


class TestExtractLastUserMessage:
    def test_extracts_last_user_message(self):
        messages = [
            {"role": "user", "content": "first"},
            {"role": "assistant", "content": "response"},
            {"role": "user", "content": "second"},
        ]
        assert _extract_last_user_message(messages) == "second"

    def test_single_user_message(self):
        messages = [{"role": "user", "content": "only one"}]
        assert _extract_last_user_message(messages) == "only one"

    def test_no_user_messages(self):
        messages = [{"role": "assistant", "content": "response"}]
        assert _extract_last_user_message(messages) is None

    def test_empty_messages(self):
        assert _extract_last_user_message([]) is None

    def test_none_messages(self):
        assert _extract_last_user_message(None) is None

    def test_messages_as_dict(self):
        """messages field might be a dict instead of list in edge cases."""
        assert _extract_last_user_message({}) is None
```

- [ ] **Step 2: Run test to verify it fails**

```bash
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py::TestExtractLastUserMessage -v
```

- [ ] **Step 3: Implement `_extract_last_user_message` in temporal.py**

Replace the entire `ai-safety-dev/src/behavioral/temporal.py` with:

```python
"""Stage 1: Temporal metrics from SpendLogs."""

import logging
from datetime import datetime, timedelta, UTC

from sqlalchemy import select, and_, func

from database import Session
from database.models import LiteLLM_SpendLogs

logger = logging.getLogger(__name__)

NIGHT_HOURS = {22, 23, 0, 1, 2, 3}


def _extract_last_user_message(messages) -> str | None:
    """Extract the last user message from a cumulative messages array.

    SpendLogs stores the full conversation history per row.
    The current user message is the last element with role='user'.
    """
    if not messages or not isinstance(messages, list):
        return None
    for msg in reversed(messages):
        if isinstance(msg, dict) and msg.get("role") == "user":
            return msg.get("content")
    return None


async def _fetch_spendlogs_rows(
    end_user_id: str, since: datetime
) -> list[tuple[datetime, list]]:
    """Fetch (startTime, messages) pairs from SpendLogs for a user since a cutoff."""
    async with Session() as session:
        query = (
            select(
                LiteLLM_SpendLogs.startTime,
                LiteLLM_SpendLogs.messages,
            )
            .where(
                and_(
                    LiteLLM_SpendLogs.end_user == end_user_id,
                    LiteLLM_SpendLogs.startTime >= since,
                )
            )
            .order_by(LiteLLM_SpendLogs.startTime.asc())
        )
        result = await session.execute(query)
        return [(row[0], row[1]) for row in result.all()]


async def compute_temporal_metrics(end_user_id: str) -> dict:
    """Compute 24h temporal metrics for a user from SpendLogs.

    Returns a dict with all Stage 1 metric fields.
    """
    now = datetime.now(UTC)
    since_24h = now - timedelta(hours=24)
    since_1h = now - timedelta(hours=1)

    rows = await _fetch_spendlogs_rows(end_user_id, since_24h)

    if not rows:
        return _empty_metrics()

    # Extract user messages and timestamps
    timestamps: list[datetime] = []
    user_messages: list[str] = []
    for start_time, messages_json in rows:
        msg = _extract_last_user_message(messages_json)
        if msg is not None:
            timestamps.append(start_time)
            user_messages.append(msg)

    if not timestamps:
        return _empty_metrics()

    # 1. daily_message_count
    daily_message_count = len(timestamps)

    # 2. activity_by_hour — histogram {0: N, ..., 23: N}
    activity_by_hour = {}
    for ts in timestamps:
        h = ts.hour
        activity_by_hour[h] = activity_by_hour.get(h, 0) + 1

    # 3. night_messages — hours 22, 23, 0, 1, 2, 3
    night_messages = sum(1 for ts in timestamps if ts.hour in NIGHT_HOURS)

    # 4. daily_active_hours — distinct hours with ≥1 message
    daily_active_hours = len(activity_by_hour)

    # 5. avg_prompt_length_chars
    avg_prompt_length_chars = (
        sum(len(m) for m in user_messages) / len(user_messages)
        if user_messages
        else 0
    )

    # 6. avg_inter_message_interval_min
    if len(timestamps) >= 2:
        intervals = []
        for i in range(1, len(timestamps)):
            gap = (timestamps[i] - timestamps[i - 1]).total_seconds() / 60.0
            intervals.append(gap)
        avg_inter_message_interval_min = sum(intervals) / len(intervals)
    else:
        avg_inter_message_interval_min = 0.0

    # 7. messages_last_1h
    messages_last_1h = sum(1 for ts in timestamps if ts >= since_1h)

    return {
        "daily_message_count": daily_message_count,
        "activity_by_hour": activity_by_hour,
        "night_messages": night_messages,
        "daily_active_hours": daily_active_hours,
        "avg_prompt_length_chars": round(avg_prompt_length_chars, 1),
        "avg_inter_message_interval_min": round(avg_inter_message_interval_min, 2),
        "messages_last_1h": messages_last_1h,
    }


def _empty_metrics() -> dict:
    """Return zeroed-out metrics when no data is available."""
    return {
        "daily_message_count": 0,
        "activity_by_hour": {},
        "night_messages": 0,
        "daily_active_hours": 0,
        "avg_prompt_length_chars": 0,
        "avg_inter_message_interval_min": 0,
        "messages_last_1h": 0,
    }
```

- [ ] **Step 4: Run tests to verify extraction passes**

```bash
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py::TestExtractLastUserMessage -v
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/temporal.py ai-safety-dev/tests/test_temporal_metrics.py
git commit -m "feat(temporal): implement Stage 1 message extraction and all 7 temporal metrics

Replaces stub with real SpendLogs queries and metric computations."
```

---

### Task 2: Test all 7 metrics computation

**Files:**
- Modify: `ai-safety-dev/tests/test_temporal_metrics.py`

Add tests for the metric computation logic by mocking the database rows.

- [ ] **Step 1: Add metric computation tests**

Append to `ai-safety-dev/tests/test_temporal_metrics.py`:

```python
from unittest.mock import patch, AsyncMock
from behavioral.temporal import compute_temporal_metrics


def _make_row(hour: int, minute: int, content: str, day_offset: int = 0):
    """Helper: create a (startTime, messages) tuple mimicking a SpendLogs row."""
    ts = datetime(2026, 3, 24, hour, minute, tzinfo=UTC) - timedelta(days=day_offset)
    messages = [
        {"role": "user", "content": content},
    ]
    return (ts, messages)


class TestComputeTemporalMetrics:
    @pytest.mark.asyncio
    async def test_empty_data_returns_zeros(self):
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=[]):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 0
        assert result["activity_by_hour"] == {}
        assert result["night_messages"] == 0

    @pytest.mark.asyncio
    async def test_daily_message_count(self):
        rows = [
            _make_row(10, 0, "hello"),
            _make_row(11, 0, "world"),
            _make_row(14, 30, "test"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 3

    @pytest.mark.asyncio
    async def test_activity_by_hour(self):
        rows = [
            _make_row(10, 0, "msg1"),
            _make_row(10, 30, "msg2"),
            _make_row(14, 0, "msg3"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["activity_by_hour"] == {10: 2, 14: 1}

    @pytest.mark.asyncio
    async def test_night_messages(self):
        rows = [
            _make_row(22, 0, "late"),      # night
            _make_row(23, 30, "later"),     # night
            _make_row(0, 15, "midnight"),   # night
            _make_row(1, 0, "deep night"), # night
            _make_row(10, 0, "morning"),    # not night
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["night_messages"] == 4

    @pytest.mark.asyncio
    async def test_daily_active_hours(self):
        rows = [
            _make_row(10, 0, "a"),
            _make_row(10, 30, "b"),   # same hour
            _make_row(14, 0, "c"),
            _make_row(22, 0, "d"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_active_hours"] == 3  # hours 10, 14, 22

    @pytest.mark.asyncio
    async def test_avg_prompt_length(self):
        rows = [
            _make_row(10, 0, "hi"),       # 2 chars
            _make_row(11, 0, "hello"),    # 5 chars
            _make_row(12, 0, "hey"),      # 3 chars
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        # avg = (2 + 5 + 3) / 3 = 3.333...
        assert result["avg_prompt_length_chars"] == pytest.approx(3.3, abs=0.1)

    @pytest.mark.asyncio
    async def test_avg_inter_message_interval(self):
        rows = [
            _make_row(10, 0, "a"),    # 0 min
            _make_row(10, 10, "b"),   # +10 min
            _make_row(10, 40, "c"),   # +30 min
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        # intervals: 10min, 30min → avg = 20.0
        assert result["avg_inter_message_interval_min"] == 20.0

    @pytest.mark.asyncio
    async def test_single_message_interval_is_zero(self):
        rows = [_make_row(10, 0, "alone")]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["avg_inter_message_interval_min"] == 0.0

    @pytest.mark.asyncio
    async def test_messages_last_1h(self):
        now = datetime.now(UTC)
        rows = [
            (now - timedelta(minutes=30), [{"role": "user", "content": "recent1"}]),
            (now - timedelta(minutes=10), [{"role": "user", "content": "recent2"}]),
            (now - timedelta(hours=2), [{"role": "user", "content": "old"}]),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["messages_last_1h"] == 2

    @pytest.mark.asyncio
    async def test_rows_with_no_user_messages_ignored(self):
        """SpendLogs rows with only assistant messages should be skipped."""
        rows = [
            (datetime(2026, 3, 24, 10, 0, tzinfo=UTC),
             [{"role": "assistant", "content": "bot only"}]),
            _make_row(11, 0, "real user message"),
        ]
        with patch("behavioral.temporal._fetch_spendlogs_rows", return_value=rows):
            result = await compute_temporal_metrics("user1")
        assert result["daily_message_count"] == 1
```

- [ ] **Step 2: Run tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add ai-safety-dev/tests/test_temporal_metrics.py
git commit -m "test(temporal): add comprehensive tests for all 7 temporal metrics

Covers: empty data, message count, hourly histogram, night messages,
active hours, prompt length avg, inter-message intervals, messages_last_1h,
and edge cases (no user messages, single message)."
```

---

### Task 3: Add 7-day rolling baselines and trend flags

**Files:**
- Modify: `ai-safety-dev/src/behavioral/temporal.py`
- Modify: `ai-safety-dev/tests/test_temporal_metrics.py`

The aggregator also needs to update `temporal_baselines` in the profile and detect trends. The baselines are 7-day rolling averages computed from `MetricsHistory`.

- [ ] **Step 1: Write baseline computation tests**

Append to `ai-safety-dev/tests/test_temporal_metrics.py`:

```python
from behavioral.temporal import compute_baselines, compute_trend_flags


class TestComputeBaselines:
    def test_baselines_from_history(self):
        """Average of last 7 days' metrics."""
        history = [
            {"daily_message_count": 10, "night_messages": 2, "daily_active_hours": 2,
             "avg_prompt_length_chars": 100, "avg_inter_message_interval_min": 5.0},
            {"daily_message_count": 20, "night_messages": 4, "daily_active_hours": 3,
             "avg_prompt_length_chars": 150, "avg_inter_message_interval_min": 4.0},
            {"daily_message_count": 30, "night_messages": 6, "daily_active_hours": 4,
             "avg_prompt_length_chars": 200, "avg_inter_message_interval_min": 3.0},
        ]
        baselines = compute_baselines(history)
        assert baselines["avg_daily_messages"] == 20.0
        assert baselines["avg_night_messages"] == 4.0
        assert baselines["avg_active_hours"] == 3.0
        assert baselines["avg_prompt_length"] == 150.0
        assert baselines["avg_inter_message_interval"] == 4.0

    def test_empty_history_returns_zeros(self):
        baselines = compute_baselines([])
        assert baselines["avg_daily_messages"] == 0
        assert baselines["avg_night_messages"] == 0


class TestComputeTrendFlags:
    def test_interval_shrinking_detected(self):
        """30%+ decrease in interval vs baseline = compulsive return."""
        metrics = {"avg_inter_message_interval_min": 3.0}
        baselines = {"avg_inter_message_interval": 5.0}
        flags = compute_trend_flags(metrics, baselines)
        assert "interval_shrinking" in flags

    def test_interval_stable_no_flag(self):
        metrics = {"avg_inter_message_interval_min": 4.5}
        baselines = {"avg_inter_message_interval": 5.0}
        flags = compute_trend_flags(metrics, baselines)
        assert "interval_shrinking" not in flags

    def test_message_count_trending_up(self):
        metrics = {"daily_message_count": 80}
        baselines = {"avg_daily_messages": 30}
        flags = compute_trend_flags(metrics, baselines)
        assert "message_count_trending_up" in flags

    def test_no_baselines_no_flags(self):
        metrics = {"daily_message_count": 80, "avg_inter_message_interval_min": 1.0}
        baselines = {"avg_daily_messages": 0, "avg_inter_message_interval": 0}
        flags = compute_trend_flags(metrics, baselines)
        assert flags == []
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py::TestComputeBaselines -v
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py::TestComputeTrendFlags -v
```

- [ ] **Step 3: Implement baselines and trend computation**

Add to `ai-safety-dev/src/behavioral/temporal.py` (after the existing functions):

```python
def compute_baselines(history: list[dict]) -> dict:
    """Compute 7-day rolling averages from MetricsHistory temporal_metrics snapshots.

    Args:
        history: list of temporal_metrics dicts from MetricsHistory rows (last 7 days)
    """
    if not history:
        return {
            "avg_daily_messages": 0,
            "avg_night_messages": 0,
            "avg_active_hours": 0,
            "avg_prompt_length": 0,
            "avg_inter_message_interval": 0,
        }

    n = len(history)
    return {
        "avg_daily_messages": sum(h.get("daily_message_count", 0) for h in history) / n,
        "avg_night_messages": sum(h.get("night_messages", 0) for h in history) / n,
        "avg_active_hours": sum(h.get("daily_active_hours", 0) for h in history) / n,
        "avg_prompt_length": sum(h.get("avg_prompt_length_chars", 0) for h in history) / n,
        "avg_inter_message_interval": sum(h.get("avg_inter_message_interval_min", 0) for h in history) / n,
    }


def compute_trend_flags(metrics: dict, baselines: dict) -> list[str]:
    """Detect trends by comparing current metrics to 7-day baselines.

    Returns a list of trend flag strings.
    """
    flags = []

    # Interval shrinking >30% vs baseline = compulsive return
    baseline_interval = baselines.get("avg_inter_message_interval", 0)
    current_interval = metrics.get("avg_inter_message_interval_min", 0)
    if baseline_interval > 0 and current_interval > 0:
        decrease = (baseline_interval - current_interval) / baseline_interval
        if decrease > 0.3:
            flags.append("interval_shrinking")

    # Message count trending up (>50% above baseline)
    baseline_msgs = baselines.get("avg_daily_messages", 0)
    current_msgs = metrics.get("daily_message_count", 0)
    if baseline_msgs > 0 and current_msgs > baseline_msgs * 1.5:
        flags.append("message_count_trending_up")

    return flags
```

- [ ] **Step 4: Run all tests**

```bash
cd ai-safety-dev && py -m pytest tests/test_temporal_metrics.py -v
```

Expected: all tests pass.

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/temporal.py ai-safety-dev/tests/test_temporal_metrics.py
git commit -m "feat(temporal): add 7-day rolling baselines and trend flag detection

Baselines computed from MetricsHistory snapshots. Trend flags:
interval_shrinking (>30% decrease) and message_count_trending_up (>50% above baseline)."
```

---

### Task 4: Wire baselines into aggregator

**Files:**
- Modify: `ai-safety-dev/src/behavioral/aggregator.py`

The aggregator currently writes `temporal_baselines={}`. Now it should compute baselines from recent MetricsHistory and store them in the profile.

- [ ] **Step 1: Update aggregator to compute and store baselines**

In `ai-safety-dev/src/behavioral/aggregator.py`, add import:

```python
from behavioral.temporal import compute_temporal_metrics, compute_baselines, compute_trend_flags
```

(Replace the existing `from behavioral.temporal import compute_temporal_metrics` line.)

Then update `run_aggregator_for_user` — after Stage 1 completes, compute baselines:

```python
    # Stage 1
    temporal_metrics = await compute_temporal_metrics(end_user_id)
    logger.info("Stage 1 complete for %s", end_user_id)

    # Baselines: 7-day rolling avg from MetricsHistory
    recent_history = await repo.get_recent_metrics(end_user_id, days=7)
    past_temporal = [h.temporal_metrics for h in recent_history if h.temporal_metrics]
    baselines = compute_baselines(past_temporal)
    trend_flags = compute_trend_flags(temporal_metrics, baselines)
    if trend_flags:
        logger.info("Trend flags for %s: %s", end_user_id, trend_flags)
```

And update the profile creation to use computed baselines:

```python
    profile = UserBehaviorProfile(
        end_user_id=end_user_id,
        risk_zone=risk_zone,
        danger_class_scores=danger_class_agg,
        behavioral_scores=behavioral_scores,
        temporal_summary=temporal_metrics,
        temporal_baselines=baselines,
        last_assessed_at=now,
        updated_at=now,
    )
```

- [ ] **Step 2: Update aggregator test**

In `ai-safety-dev/tests/test_aggregator_skeleton.py`, update `test_pipeline_runs_all_stages` to mock `get_recent_metrics`:

Add to mock_repo setup:
```python
mock_repo.get_recent_metrics.return_value = []
```

- [ ] **Step 3: Run all tests**

```bash
cd ai-safety-dev && py -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/src/behavioral/aggregator.py ai-safety-dev/tests/test_aggregator_skeleton.py
git commit -m "feat(aggregator): wire 7-day baselines and trend flags into pipeline

Baselines computed from MetricsHistory after Stage 1.
Trend flags stored for future use by risk engine (Milestone 5)."
```
