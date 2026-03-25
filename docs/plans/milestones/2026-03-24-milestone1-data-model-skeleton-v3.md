# Milestone 1: Data Model + Skeleton — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Create the 4 behavioral monitoring tables, the `behavioral/` module skeleton with empty pipeline stages, wire the daily aggregator into the app, and add `BEHAVIORAL_LLM_MODEL` config.

**Architecture:** Follows the existing codebase patterns — SQLAlchemy 2.0 models inheriting from `Base`, async repository with `Session`, APScheduler for daily jobs, Starlette middleware. The `behavioral/` package lives inside `ai-safety-dev/src/` alongside existing modules. Schema creation uses the existing `create_all_schemas()` which calls `Base.metadata.create_all` — new models auto-register by importing them before that call.

**Note on migrations:** The spec says "Alembic migrations" but the existing codebase uses Prisma + `Base.metadata.create_all` for schema management. This plan follows the existing pattern (`create_all_schemas()`). Alembic setup can be added later if upgrade/downgrade versioning is needed.

**Tech Stack:** SQLAlchemy 2.0 (async), asyncpg, APScheduler, Pydantic, pytest + pytest-asyncio

**Spec:** `docs/plans/2026-03-24-sophiya-behavioral-monitoring-roadmap-v3.md`

---

## File Structure

```
ai-safety-dev/src/behavioral/
├── __init__.py              # Package init, exports
├── models.py                # 4 SQLAlchemy models
├── repository.py            # BehavioralRepository (CRUD for all 4 tables)
├── aggregator.py            # Pipeline orchestrator (calls stages 1-4 sequentially)
├── temporal.py              # Stage 1 stub
├── danger_agg.py            # Stage 2 stub
├── behavioral_llm.py        # Stage 3 stub
├── risk_engine.py           # Stage 4 stub
├── weekly_report.py         # Weekly report stub
└── scheduler.py             # Daily APScheduler job

ai-safety-dev/src/config.py           # Add BEHAVIORAL_LLM_MODEL
ai-safety-dev/src/main.py             # Wire behavioral scheduler into lifespan
ai-safety-dev/src/database/models.py  # Import behavioral models for auto-registration

ai-safety-dev/tests/
├── conftest.py                        # Shared fixtures (async engine, session, test DB)
├── test_behavioral_models.py          # Model creation + constraint tests
├── test_behavioral_repository.py      # Repository CRUD tests
└── test_aggregator_skeleton.py        # Pipeline runs end-to-end with stubs
```

---

### Task 1: Create behavioral models

**Files:**
- Create: `ai-safety-dev/src/behavioral/__init__.py`
- Create: `ai-safety-dev/src/behavioral/models.py`

- [ ] **Step 1: Create `behavioral/__init__.py`**

```python
"""Behavioral monitoring system — daily aggregation pipeline."""
```

- [ ] **Step 2: Create `behavioral/models.py` with all 4 tables**

```python
from sqlalchemy import (
    Boolean, Date, DateTime, ForeignKey, Integer, JSON, String, Text, text,
    UniqueConstraint,
)
from sqlalchemy.orm import mapped_column

from database.models import Base


class UserBehaviorProfile(Base):
    """Current risk state per user. Read by soft middleware and weekly report."""

    __tablename__ = "UserBehaviorProfile"

    end_user_id = mapped_column(
        String,
        ForeignKey("LiteLLM_UserTable.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        primary_key=True,
    )
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))
    danger_class_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    behavioral_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    temporal_summary = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    temporal_baselines = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    last_assessed_at = mapped_column(DateTime, nullable=True)
    updated_at = mapped_column(DateTime, nullable=True, server_default=text("CURRENT_TIMESTAMP"))


class MetricsHistory(Base):
    """Daily timestamped snapshots for trend charts and weekly report."""

    __tablename__ = "MetricsHistory"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(
        String,
        ForeignKey("LiteLLM_UserTable.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    computed_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    period_type = mapped_column(String, nullable=False, server_default=text("'daily'"))
    temporal_metrics = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    danger_class_agg = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    behavioral_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))


class DailySummary(Base):
    """Structured daily narrative per user. Read by Stage 3 (calendar) and weekly report."""

    __tablename__ = "DailySummary"
    __table_args__ = (
        UniqueConstraint("end_user_id", "summary_date", name="uq_daily_summary_user_date"),
    )

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(
        String,
        ForeignKey("LiteLLM_UserTable.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    summary_date = mapped_column(Date, nullable=False)
    key_topics = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    life_events = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    emotional_tone = mapped_column(String, nullable=False, server_default=text("'neutral'"))
    ai_relationship_markers = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    notable_quotes = mapped_column(JSON, nullable=False, server_default=text("'[]'"))
    operator_note = mapped_column(Text, nullable=True)
    is_notable = mapped_column(Boolean, nullable=False, server_default=text("false"))
    created_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))


class BehavioralEvent(Base):
    """Discrete threshold crossings for alerts and audit trail."""

    __tablename__ = "BehavioralEvents"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(
        String,
        ForeignKey("LiteLLM_UserTable.user_id", ondelete="CASCADE", onupdate="CASCADE"),
        nullable=False,
    )
    detected_at = mapped_column(DateTime, nullable=False, server_default=text("CURRENT_TIMESTAMP"))
    event_type = mapped_column(String, nullable=False)
    severity = mapped_column(String, nullable=False)
    details = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    acknowledged = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

- [ ] **Step 3: Register behavioral models in database/__init__.py**

Add the import inside `create_all_schemas()` in `ai-safety-dev/src/database/__init__.py` (lazy import avoids circular dependency since `behavioral/models.py` imports `Base` from `database/models.py`):

```python
async def create_all_schemas():
    import behavioral.models  # noqa: F401 — registers tables with Base.metadata
    async with engine.begin() as conn:
        await asyncio.sleep(1)
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()
```

This ensures `create_all_schemas()` picks up the new tables without circular imports.

- [ ] **Step 4: Verify tables are created**

Run the app briefly or use a script to confirm all 4 tables appear:

```bash
cd ai-safety-dev/src && python -c "
import asyncio
from database import create_all_schemas
asyncio.run(create_all_schemas())
print('Tables created successfully')
"
```

- [ ] **Step 5: Commit**

```bash
git add ai-safety-dev/src/behavioral/__init__.py ai-safety-dev/src/behavioral/models.py ai-safety-dev/src/database/models.py
git commit -m "feat(behavioral): add 4 SQLAlchemy models for behavioral monitoring

Tables: UserBehaviorProfile, MetricsHistory, DailySummary, BehavioralEvents
Registered with Base.metadata for auto-creation via create_all_schemas()."
```

---

### Task 2: Create behavioral repository

**Files:**
- Create: `ai-safety-dev/src/behavioral/repository.py`

- [ ] **Step 1: Create `behavioral/repository.py`**

```python
from datetime import date, datetime, timedelta, UTC

from sqlalchemy import select, and_

from database import Session
from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)


class BehavioralRepository:
    """DB access layer for all behavioral monitoring tables."""

    def __init__(self):
        self.session = Session()

    # --- UserBehaviorProfile ---

    async def get_profile(self, end_user_id: str) -> UserBehaviorProfile | None:
        async with self.session as session:
            return await session.get(UserBehaviorProfile, end_user_id)

    async def upsert_profile(self, profile: UserBehaviorProfile) -> None:
        async with self.session as session:
            async with session.begin():
                await session.merge(profile)

    async def get_risk_zone(self, end_user_id: str) -> str | None:
        """Fast lookup for middleware — returns risk_zone or None if no profile."""
        async with self.session as session:
            query = (
                select(UserBehaviorProfile.risk_zone)
                .where(UserBehaviorProfile.end_user_id == end_user_id)
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            return row

    # --- MetricsHistory ---

    async def add_metrics_history(self, entry: MetricsHistory) -> None:
        async with self.session as session:
            async with session.begin():
                session.add(entry)

    async def get_recent_metrics(
        self, end_user_id: str, days: int = 7
    ) -> list[MetricsHistory]:
        async with self.session as session:
            cutoff = datetime.now(UTC).replace(
                hour=0, minute=0, second=0, microsecond=0
            )
            cutoff = cutoff - timedelta(days=days)
            query = (
                select(MetricsHistory)
                .where(
                    and_(
                        MetricsHistory.end_user_id == end_user_id,
                        MetricsHistory.computed_at >= cutoff,
                    )
                )
                .order_by(MetricsHistory.computed_at.desc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    # --- DailySummary ---

    async def add_daily_summary(self, summary: DailySummary) -> None:
        async with self.session as session:
            async with session.begin():
                await session.merge(summary)

    async def get_notable_calendar(
        self, end_user_id: str, limit: int = 14
    ) -> list[DailySummary]:
        """Fetch notable days for Stage 3 calendar context."""
        async with self.session as session:
            query = (
                select(DailySummary)
                .where(
                    and_(
                        DailySummary.end_user_id == end_user_id,
                        DailySummary.is_notable == True,  # noqa: E712
                    )
                )
                .order_by(DailySummary.summary_date.desc())
                .limit(limit)
            )
            result = await session.execute(query)
            return list(result.scalars().all())

    # --- BehavioralEvents ---

    async def add_event(self, event: BehavioralEvent) -> None:
        async with self.session as session:
            async with session.begin():
                session.add(event)

    async def get_recent_events(
        self, end_user_id: str, days: int = 7
    ) -> list[BehavioralEvent]:
        async with self.session as session:
            cutoff = datetime.now(UTC) - timedelta(days=days)
            query = (
                select(BehavioralEvent)
                .where(
                    and_(
                        BehavioralEvent.end_user_id == end_user_id,
                        BehavioralEvent.detected_at >= cutoff,
                    )
                )
                .order_by(BehavioralEvent.detected_at.desc())
            )
            result = await session.execute(query)
            return list(result.scalars().all())
```

- [ ] **Step 2: Commit**

```bash
git add ai-safety-dev/src/behavioral/repository.py
git commit -m "feat(behavioral): add BehavioralRepository with CRUD for all 4 tables"
```

---

### Task 3: Add BEHAVIORAL_LLM_MODEL to config

**Files:**
- Modify: `ai-safety-dev/src/config.py`

- [ ] **Step 1: Add setting to config.py**

Add to the `Settings` class in `ai-safety-dev/src/config.py`:

```python
BEHAVIORAL_LLM_MODEL: str = "openai/gpt-oss-safeguard-20b"
```

Add it after the existing `JUDGE_MODEL` field. Uses the same default as the judge model — the user can override via env var `BEHAVIORAL_LLM_MODEL`.

- [ ] **Step 2: Commit**

```bash
git add ai-safety-dev/src/config.py
git commit -m "feat(config): add BEHAVIORAL_LLM_MODEL setting for Stage 3 LLM backend"
```

---

### Task 4: Create pipeline stage stubs

**Files:**
- Create: `ai-safety-dev/src/behavioral/temporal.py`
- Create: `ai-safety-dev/src/behavioral/danger_agg.py`
- Create: `ai-safety-dev/src/behavioral/behavioral_llm.py`
- Create: `ai-safety-dev/src/behavioral/risk_engine.py`
- Create: `ai-safety-dev/src/behavioral/weekly_report.py`

Each stub returns empty/default data. They will be implemented in Milestones 2-6.

- [ ] **Step 1: Create `behavioral/temporal.py` (Stage 1 stub)**

```python
"""Stage 1: Temporal metrics from SpendLogs. Implemented in Milestone 2."""

import logging

logger = logging.getLogger(__name__)


async def compute_temporal_metrics(end_user_id: str) -> dict:
    """Compute 24h temporal metrics for a user. Returns temporal_metrics JSON.

    Stub: returns empty metrics. Full implementation in Milestone 2.
    """
    logger.info("Stage 1 (temporal): stub for user %s", end_user_id)
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

- [ ] **Step 2: Create `behavioral/danger_agg.py` (Stage 2 stub)**

```python
"""Stage 2: Danger class aggregation from PredictTable. Implemented in Milestone 3."""

import logging

logger = logging.getLogger(__name__)


async def compute_danger_class_agg(end_user_id: str) -> dict:
    """Aggregate 24h danger class scores for a user. Returns danger_class_agg JSON.

    Stub: returns empty scores. Full implementation in Milestone 3.
    """
    logger.info("Stage 2 (danger_agg): stub for user %s", end_user_id)
    return {
        "self_harm_avg": 0.0,
        "self_harm_max": 0.0,
        "self_harm_flag_rate": 0.0,
        "psychosis_avg": 0.0,
        "delusion_avg": 0.0,
        "delusion_flag_rate": 0.0,
        "obsession_avg": 0.0,
        "anthropomorphism_avg": 0.0,
        "max_class_avg": 0.0,
    }
```

- [ ] **Step 3: Create `behavioral/behavioral_llm.py` (Stage 3 stub)**

```python
"""Stage 3: Behavioral LLM scores + daily summary. Implemented in Milestone 4."""

import logging
from datetime import date

logger = logging.getLogger(__name__)


async def compute_behavioral_scores_and_summary(
    end_user_id: str,
    today: date | None = None,
) -> dict:
    """Run LLM analysis on recent messages + calendar. Returns scores + summary.

    Stub: returns default scores and empty summary. Full implementation in Milestone 4.
    """
    logger.info("Stage 3 (behavioral_llm): stub for user %s", end_user_id)
    return {
        "scores": {
            "topic_concentration": 0.0,
            "decision_delegation": 0.0,
            "social_isolation": 0.0,
            "emotional_attachment": 0.0,
        },
        "summary": {
            "key_topics": [],
            "life_events": [],
            "emotional_tone": "neutral",
            "ai_relationship_markers": [],
            "notable_quotes": [],
            "operator_note": None,
        },
    }
```

- [ ] **Step 4: Create `behavioral/risk_engine.py` (Stage 4 stub)**

```python
"""Stage 4: Risk zone engine. Implemented in Milestone 5."""

import logging

logger = logging.getLogger(__name__)


async def evaluate_risk_zone(
    temporal_metrics: dict,
    danger_class_agg: dict,
    behavioral_scores: dict,
) -> tuple[str, list[str]]:
    """Evaluate risk zone from all stage outputs. Returns (zone, triggered_rules).

    Stub: returns GREEN with no triggers. Full implementation in Milestone 5.
    """
    logger.info("Stage 4 (risk_engine): stub — returning GREEN")
    return "GREEN", []
```

- [ ] **Step 5: Create `behavioral/weekly_report.py` (Milestone 6 stub)**

```python
"""Weekly report generator. Implemented in Milestone 6."""

import logging

logger = logging.getLogger(__name__)


async def generate_weekly_report(end_user_id: str) -> str:
    """Generate weekly report for a user. Returns formatted report string.

    Stub: returns placeholder. Full implementation in Milestone 6.
    """
    logger.info("Weekly report: stub for user %s", end_user_id)
    return f"[Weekly report stub for {end_user_id}]"
```

- [ ] **Step 6: Commit**

```bash
git add ai-safety-dev/src/behavioral/temporal.py ai-safety-dev/src/behavioral/danger_agg.py ai-safety-dev/src/behavioral/behavioral_llm.py ai-safety-dev/src/behavioral/risk_engine.py ai-safety-dev/src/behavioral/weekly_report.py
git commit -m "feat(behavioral): add pipeline stage stubs (Stages 1-4 + weekly report)

Each stub returns default/empty data. Will be implemented in Milestones 2-6."
```

---

### Task 5: Create aggregator pipeline orchestrator

**Files:**
- Create: `ai-safety-dev/src/behavioral/aggregator.py`

- [ ] **Step 1: Create `behavioral/aggregator.py`**

```python
"""Main aggregator pipeline — runs daily per user, executes Stages 1-4 sequentially."""

import logging
from datetime import datetime, date, UTC

from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)
from behavioral.repository import BehavioralRepository
from behavioral.temporal import compute_temporal_metrics
from behavioral.danger_agg import compute_danger_class_agg
from behavioral.behavioral_llm import compute_behavioral_scores_and_summary
from behavioral.risk_engine import evaluate_risk_zone

logger = logging.getLogger(__name__)


async def run_aggregator_for_user(end_user_id: str) -> None:
    """Execute the full 4-stage pipeline for a single user.

    1. Stage 1: Temporal metrics (pure SQL from SpendLogs)
    2. Stage 2: Danger class aggregation (pure SQL from PredictTable)
    3. Stage 3: Behavioral LLM scores + daily summary
    4. Stage 4: Risk zone engine

    After all stages: write MetricsHistory, DailySummary, update UserBehaviorProfile,
    and optionally write BehavioralEvent if zone changed.
    """
    repo = BehavioralRepository()
    today = date.today()
    now = datetime.now(UTC)

    logger.info("Aggregator starting for user %s", end_user_id)

    # Stage 1
    temporal_metrics = await compute_temporal_metrics(end_user_id)
    logger.info("Stage 1 complete for %s", end_user_id)

    # Stage 2
    danger_class_agg = await compute_danger_class_agg(end_user_id)
    logger.info("Stage 2 complete for %s", end_user_id)

    # Stage 3
    stage3_result = await compute_behavioral_scores_and_summary(end_user_id, today)
    behavioral_scores = stage3_result["scores"]
    summary_data = stage3_result["summary"]
    logger.info("Stage 3 complete for %s", end_user_id)

    # Stage 4
    risk_zone, triggered_rules = await evaluate_risk_zone(
        temporal_metrics, danger_class_agg, behavioral_scores
    )
    logger.info("Stage 4 complete for %s: zone=%s, triggers=%s", end_user_id, risk_zone, triggered_rules)

    # --- Post-stage writes ---

    # 1. Write MetricsHistory
    metrics_entry = MetricsHistory(
        end_user_id=end_user_id,
        computed_at=now,
        period_type="daily",
        temporal_metrics=temporal_metrics,
        danger_class_agg=danger_class_agg,
        behavioral_scores=behavioral_scores,
        risk_zone=risk_zone,
    )
    await repo.add_metrics_history(metrics_entry)

    # 2. Write DailySummary
    is_notable = _compute_is_notable(summary_data, behavioral_scores)
    daily_summary = DailySummary(
        end_user_id=end_user_id,
        summary_date=today,
        key_topics=summary_data["key_topics"],
        life_events=summary_data["life_events"],
        emotional_tone=summary_data["emotional_tone"],
        ai_relationship_markers=summary_data["ai_relationship_markers"],
        notable_quotes=summary_data["notable_quotes"],
        operator_note=summary_data["operator_note"],
        is_notable=is_notable,
    )
    await repo.add_daily_summary(daily_summary)

    # 3. Update UserBehaviorProfile
    old_profile = await repo.get_profile(end_user_id)
    old_zone = old_profile.risk_zone if old_profile else "GREEN"

    profile = UserBehaviorProfile(
        end_user_id=end_user_id,
        risk_zone=risk_zone,
        danger_class_scores=danger_class_agg,
        behavioral_scores=behavioral_scores,
        temporal_summary=temporal_metrics,
        temporal_baselines={},  # TODO: compute 7-day rolling avg in Milestone 2
        last_assessed_at=now,
        updated_at=now,
    )
    await repo.upsert_profile(profile)

    # 4. Write BehavioralEvent if zone changed or RED
    if risk_zone != old_zone:
        event = BehavioralEvent(
            end_user_id=end_user_id,
            detected_at=now,
            event_type="risk_zone_change",
            severity=risk_zone,
            details={
                "old_zone": old_zone,
                "new_zone": risk_zone,
                "triggered_rules": triggered_rules,
            },
        )
        await repo.add_event(event)
        logger.info("Zone change event: %s -> %s for %s", old_zone, risk_zone, end_user_id)

    logger.info("Aggregator complete for user %s", end_user_id)


def _compute_is_notable(summary_data: dict, behavioral_scores: dict) -> bool:
    """Determine if today's summary is notable for calendar filtering."""
    if summary_data.get("life_events"):
        return True
    if summary_data.get("ai_relationship_markers"):
        return True
    tone = summary_data.get("emotional_tone", "neutral")
    if tone not in ("neutral", "calm", "normal"):
        return True
    if behavioral_scores.get("topic_concentration", 0) > 0.7:
        return True
    if behavioral_scores.get("decision_delegation", 0) > 0.4:
        return True
    return False
```

- [ ] **Step 2: Commit**

```bash
git add ai-safety-dev/src/behavioral/aggregator.py
git commit -m "feat(behavioral): add aggregator pipeline orchestrator

Runs Stages 1-4 sequentially, then writes MetricsHistory, DailySummary,
updates UserBehaviorProfile, and emits BehavioralEvents on zone changes."
```

---

### Task 6: Create behavioral scheduler

**Files:**
- Create: `ai-safety-dev/src/behavioral/scheduler.py`
- Modify: `ai-safety-dev/src/main.py`

- [ ] **Step 1: Create `behavioral/scheduler.py`**

```python
"""Daily APScheduler job for behavioral aggregation."""

import logging
from datetime import timezone

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.cron import CronTrigger
from apscheduler.triggers.interval import IntervalTrigger

from sqlalchemy import select, distinct

from config import settings
from database import Session
from database.models import LiteLLM_SpendLogs
from behavioral.aggregator import run_aggregator_for_user

logger = logging.getLogger(__name__)


async def _get_active_user_ids() -> list[str]:
    """Fetch distinct end_user IDs from SpendLogs."""
    async with Session() as session:
        query = select(distinct(LiteLLM_SpendLogs.end_user)).where(
            LiteLLM_SpendLogs.end_user.is_not(None)
        )
        result = await session.execute(query)
        return [row[0] for row in result.all()]


async def _run_daily_aggregation():
    """Run aggregator for all active users."""
    user_ids = await _get_active_user_ids()
    logger.info("Daily behavioral aggregation: processing %d users", len(user_ids))
    for user_id in user_ids:
        try:
            await run_aggregator_for_user(user_id)
        except Exception:
            logger.exception("Aggregator failed for user %s", user_id)


async def start_behavioral_scheduler() -> AsyncIOScheduler:
    """Start the daily behavioral aggregation scheduler."""
    scheduler = AsyncIOScheduler(timezone=timezone.utc)

    if settings.is_develop_mode:
        trigger = IntervalTrigger(seconds=30)
        logger.info("Behavioral scheduler: dev mode, running every 30s")
    else:
        trigger = CronTrigger(hour=0, minute=30)
        logger.info("Behavioral scheduler: production, running daily at 00:30 UTC")

    scheduler.add_job(
        _run_daily_aggregation,
        trigger,
        id="behavioral_daily_aggregation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=3600,
    )

    scheduler.start()
    return scheduler
```

- [ ] **Step 2: Wire into `main.py`**

In `ai-safety-dev/src/main.py`, modify the `wrapped_lifespan` function. Add import at top:

```python
from behavioral.scheduler import start_behavioral_scheduler
```

Update `wrapped_lifespan`:

```python
@asynccontextmanager
async def wrapped_lifespan(app_):
    await create_all_schemas()
    scheduler = await start_langfuse_scheduler()
    behavioral_scheduler = await start_behavioral_scheduler()
    try:
        async with old(app_) as _:
            yield
    finally:
        behavioral_scheduler.shutdown(wait=False)
        scheduler.shutdown(wait=False)
```

- [ ] **Step 3: Commit**

```bash
git add ai-safety-dev/src/behavioral/scheduler.py ai-safety-dev/src/main.py
git commit -m "feat(behavioral): wire daily aggregator scheduler into app lifespan

Runs daily at 00:30 UTC (production) or every 30s (dev mode).
Iterates all active users from SpendLogs."
```

---

### Task 7: Install test dependencies

**Files:**
- Modify: `ai-safety-dev/pyproject.toml`

- [ ] **Step 1: Add test dependencies**

```bash
cd ai-safety-dev && pip install pytest pytest-asyncio aiosqlite
```

Add pytest config to `pyproject.toml`:

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
pythonpath = ["src"]
```

- [ ] **Step 2: Commit**

```bash
git add ai-safety-dev/pyproject.toml
git commit -m "chore: add pytest + pytest-asyncio + aiosqlite test dependencies"
```

---

### Task 8: Set up test infrastructure + write model tests

**Files:**
- Create: `ai-safety-dev/tests/conftest.py`
- Create: `ai-safety-dev/tests/test_behavioral_models.py`

- [ ] **Step 1: Create `ai-safety-dev/tests/conftest.py`**

```python
"""Shared test fixtures for behavioral monitoring tests."""

import asyncio
import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base


@pytest.fixture(scope="session")
def event_loop():
    loop = asyncio.new_event_loop()
    yield loop
    loop.close()


@pytest_asyncio.fixture(scope="session")
async def test_engine():
    """Create an in-memory SQLite engine for tests.

    Note: SQLite does not support all PostgreSQL features.
    For full integration tests, use a test PostgreSQL database.
    """
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    await engine.dispose()


@pytest_asyncio.fixture
async def test_session(test_engine):
    """Provide a fresh async session per test."""
    session_factory = async_sessionmaker(
        bind=test_engine, class_=AsyncSession, expire_on_commit=False
    )
    async with session_factory() as session:
        yield session
        await session.rollback()
```

- [ ] **Step 2: Create `ai-safety-dev/tests/test_behavioral_models.py`**

```python
"""Tests for behavioral monitoring SQLAlchemy models."""

import pytest
from datetime import date, datetime, UTC

from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)


class TestUserBehaviorProfile:
    def test_create_with_defaults(self):
        profile = UserBehaviorProfile(end_user_id="user_001")
        assert profile.end_user_id == "user_001"
        assert profile.risk_zone is None  # server_default, not Python default

    def test_create_with_all_fields(self):
        profile = UserBehaviorProfile(
            end_user_id="user_001",
            risk_zone="YELLOW",
            danger_class_scores={"self_harm_avg": 0.3},
            behavioral_scores={"topic_concentration": 0.8},
            temporal_summary={"daily_message_count": 50},
            temporal_baselines={"avg_daily_messages": 20},
            last_assessed_at=datetime.now(UTC),
        )
        assert profile.risk_zone == "YELLOW"
        assert profile.danger_class_scores["self_harm_avg"] == 0.3


class TestMetricsHistory:
    def test_create(self):
        entry = MetricsHistory(
            end_user_id="user_001",
            temporal_metrics={"daily_message_count": 42},
            danger_class_agg={"self_harm_avg": 0.1},
            behavioral_scores={"topic_concentration": 0.5},
            risk_zone="GREEN",
        )
        assert entry.end_user_id == "user_001"
        assert entry.temporal_metrics["daily_message_count"] == 42


class TestDailySummary:
    def test_create(self):
        summary = DailySummary(
            end_user_id="user_001",
            summary_date=date(2026, 3, 24),
            key_topics=["work stress", "insomnia"],
            life_events=["breakup with partner"],
            emotional_tone="anxious",
            ai_relationship_markers=["called AI 'my friend'"],
            notable_quotes=["я больше не могу"],
            operator_note="Second mention of work problems",
            is_notable=True,
        )
        assert summary.summary_date == date(2026, 3, 24)
        assert summary.is_notable is True
        assert len(summary.key_topics) == 2

    def test_create_unremarkable_day(self):
        summary = DailySummary(
            end_user_id="user_001",
            summary_date=date(2026, 3, 23),
            key_topics=["daily tasks"],
            life_events=[],
            emotional_tone="neutral",
            ai_relationship_markers=[],
            notable_quotes=[],
            is_notable=False,
        )
        assert summary.is_notable is False


class TestBehavioralEvent:
    def test_create_zone_change(self):
        event = BehavioralEvent(
            end_user_id="user_001",
            event_type="risk_zone_change",
            severity="YELLOW",
            details={
                "old_zone": "GREEN",
                "new_zone": "YELLOW",
                "triggered_rules": ["night_messages > 24", "topic_concentration > 0.7"],
            },
        )
        assert event.event_type == "risk_zone_change"
        assert len(event.details["triggered_rules"]) == 2
```

- [ ] **Step 3: Run tests**

```bash
cd ai-safety-dev && python -m pytest tests/test_behavioral_models.py -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/tests/conftest.py ai-safety-dev/tests/test_behavioral_models.py
git commit -m "test(behavioral): add model unit tests and test infrastructure

Tests cover model creation for all 4 tables with various field combinations.
Uses in-memory SQLite for fast tests."
```

---

### Task 9: Write aggregator skeleton test

**Files:**
- Create: `ai-safety-dev/tests/test_aggregator_skeleton.py`

- [ ] **Step 1: Create `ai-safety-dev/tests/test_aggregator_skeleton.py`**

```python
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
```

- [ ] **Step 2: Run tests**

```bash
cd ai-safety-dev && python -m pytest tests/test_aggregator_skeleton.py -v
```

Expected: all tests pass.

- [ ] **Step 3: Commit**

```bash
git add ai-safety-dev/tests/test_aggregator_skeleton.py
git commit -m "test(behavioral): add aggregator pipeline and is_notable tests

Covers: all 4 stages called, post-write to all tables, zone change events,
and is_notable filtering logic with 8 edge cases."
```

---

### Task 10: Write repository CRUD tests

**Files:**
- Create: `ai-safety-dev/tests/test_behavioral_repository.py`

- [ ] **Step 1: Create `ai-safety-dev/tests/test_behavioral_repository.py`**

```python
"""Tests for BehavioralRepository — database round-trip tests."""

import pytest
from datetime import date, datetime, UTC

from behavioral.models import (
    UserBehaviorProfile,
    MetricsHistory,
    DailySummary,
    BehavioralEvent,
)
from behavioral.repository import BehavioralRepository


class TestProfileCRUD:
    @pytest.mark.asyncio
    async def test_upsert_and_get_profile(self):
        repo = BehavioralRepository()
        profile = UserBehaviorProfile(
            end_user_id="test_repo_user",
            risk_zone="GREEN",
            danger_class_scores={},
            behavioral_scores={},
            temporal_summary={},
            temporal_baselines={},
            last_assessed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.upsert_profile(profile)
        fetched = await repo.get_profile("test_repo_user")
        assert fetched is not None
        assert fetched.risk_zone == "GREEN"

    @pytest.mark.asyncio
    async def test_get_risk_zone(self):
        repo = BehavioralRepository()
        profile = UserBehaviorProfile(
            end_user_id="test_zone_user",
            risk_zone="YELLOW",
            danger_class_scores={},
            behavioral_scores={},
            temporal_summary={},
            temporal_baselines={},
            last_assessed_at=datetime.now(UTC),
            updated_at=datetime.now(UTC),
        )
        await repo.upsert_profile(profile)
        zone = await repo.get_risk_zone("test_zone_user")
        assert zone == "YELLOW"

    @pytest.mark.asyncio
    async def test_get_risk_zone_missing_user(self):
        repo = BehavioralRepository()
        zone = await repo.get_risk_zone("nonexistent_user")
        assert zone is None


class TestNotableCalendar:
    @pytest.mark.asyncio
    async def test_get_notable_calendar_filters_unremarkable(self):
        repo = BehavioralRepository()
        # notable day
        await repo.add_daily_summary(DailySummary(
            end_user_id="test_cal_user",
            summary_date=date(2026, 3, 20),
            key_topics=["work stress"],
            life_events=["argument"],
            emotional_tone="frustrated",
            ai_relationship_markers=[],
            notable_quotes=[],
            is_notable=True,
        ))
        # unremarkable day
        await repo.add_daily_summary(DailySummary(
            end_user_id="test_cal_user",
            summary_date=date(2026, 3, 21),
            key_topics=["daily tasks"],
            life_events=[],
            emotional_tone="neutral",
            ai_relationship_markers=[],
            notable_quotes=[],
            is_notable=False,
        ))
        results = await repo.get_notable_calendar("test_cal_user")
        assert len(results) == 1
        assert results[0].summary_date == date(2026, 3, 20)


class TestMetricsHistoryCRUD:
    @pytest.mark.asyncio
    async def test_add_and_get_recent(self):
        repo = BehavioralRepository()
        entry = MetricsHistory(
            end_user_id="test_hist_user",
            computed_at=datetime.now(UTC),
            temporal_metrics={"daily_message_count": 42},
            danger_class_agg={},
            behavioral_scores={},
            risk_zone="GREEN",
        )
        await repo.add_metrics_history(entry)
        results = await repo.get_recent_metrics("test_hist_user", days=7)
        assert len(results) >= 1
        assert results[0].temporal_metrics["daily_message_count"] == 42
```

Note: These tests require a running test database (PostgreSQL) since they do real DB operations. They will be skipped in CI if no DB is available. For local development, run against the dev database.

- [ ] **Step 2: Run tests**

```bash
cd ai-safety-dev && python -m pytest tests/test_behavioral_repository.py -v
```

- [ ] **Step 3: Run full test suite**

```bash
cd ai-safety-dev && python -m pytest tests/ -v
```

Expected: all tests pass.

- [ ] **Step 4: Commit**

```bash
git add ai-safety-dev/tests/test_behavioral_repository.py
git commit -m "test(behavioral): add repository CRUD round-trip tests

Covers: profile upsert/get, risk_zone lookup, notable calendar filtering,
metrics history add/get."
```
