# Milestone 1: Data Model + Skeleton — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create 3 new database tables (UserBehaviorProfile, MetricsHistory, BehavioralEvents), a `behavioral/` module with skeleton aggregator, and wire it into the existing APScheduler so it runs every 5 minutes.

**Architecture:** New `src/behavioral/` package alongside Mikhail's existing code. Uses the same SQLAlchemy Base, same async engine, same `Session` factory. The aggregator is an APScheduler job that queries SpendLogs + PredictTable and writes to the 3 new tables. Milestone 1 only creates the skeleton — no real computation, just the wiring.

**Tech Stack:** Python 3.12, SQLAlchemy 2.x (async), APScheduler 3.x, PostgreSQL, pytest, uv

**Existing code context:**
- DB engine + session: `src/database/__init__.py` — `engine`, `Session`, `create_all_schemas()`
- All models inherit from `src/database/models.py:Base`
- Scheduler: `src/scheduler.py` — `start_langfuse_scheduler()` returns `AsyncIOScheduler`
- App wiring: `src/main.py` — lifespan creates schemas then starts scheduler
- Config: `src/config.py` — `Settings` (pydantic-settings), `settings` singleton
- Repository pattern: `src/database/repository.py` — `PredictRepository`
- Key tables to read from: `LiteLLM_SpendLogs` (columns: `end_user`, `startTime`, `endTime`, `messages`, `model`, `session_id`), `LiteLLM_PredictTable` (columns: `user_id`, `session_id`, `predict` JSON, `created_at`)

---

## Task 1: Add pytest to the project

**Files:**
- Modify: `ai-safety-mikhail/pyproject.toml`
- Create: `ai-safety-mikhail/tests/__init__.py`
- Create: `ai-safety-mikhail/tests/conftest.py`

**Step 1: Add pytest + pytest-asyncio to dev dependencies**

In `pyproject.toml`, add after the `[project]` section:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
]
```

**Step 2: Create test directory and conftest**

Create `tests/__init__.py` (empty file).

Create `tests/conftest.py`:

```python
import pytest
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from database.models import Base


@pytest.fixture(scope="session")
def anyio_backend():
    return "asyncio"


@pytest.fixture(scope="function")
async def db_engine():
    """In-memory SQLite for unit tests. No real PostgreSQL needed."""
    engine = create_async_engine("sqlite+aiosqlite:///:memory:")
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield engine
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
    await engine.dispose()


@pytest.fixture(scope="function")
async def db_session(db_engine):
    """Async session bound to in-memory SQLite."""
    session_factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    async with session_factory() as session:
        yield session
```

**Step 3: Add aiosqlite dependency for test DB**

In `pyproject.toml` dev dependencies, add:

```toml
[dependency-groups]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.24",
    "aiosqlite>=0.21",
]
```

**Step 4: Install dev dependencies**

Run: `cd ai-safety-mikhail && uv sync --group dev`
Expected: resolves and installs pytest, pytest-asyncio, aiosqlite

**Step 5: Run pytest to verify setup**

Run: `cd ai-safety-mikhail && uv run pytest tests/ -v`
Expected: "no tests ran" (0 collected), exit code 5 — that's correct, we have no tests yet

**Step 6: Commit**

```bash
cd ai-safety-mikhail
git add pyproject.toml uv.lock tests/__init__.py tests/conftest.py
git commit -m "test: add pytest infrastructure with async SQLite fixture"
```

---

## Task 2: Create the 3 behavioral models

**Files:**
- Create: `ai-safety-mikhail/src/behavioral/__init__.py`
- Create: `ai-safety-mikhail/src/behavioral/models.py`
- Create: `ai-safety-mikhail/tests/test_behavioral_models.py`

**Step 1: Write the failing test**

Create `tests/test_behavioral_models.py`:

```python
import pytest
from datetime import datetime, UTC

from sqlalchemy import select

from behavioral.models import UserBehaviorProfile, MetricsHistory, BehavioralEvent


@pytest.mark.asyncio
async def test_create_user_behavior_profile(db_session):
    profile = UserBehaviorProfile(
        end_user_id="test_user_1",
        risk_zone="GREEN",
        danger_class_scores={"self_harm": 0.0, "psychosis": 0.0, "delusion": 0.0, "obsession": 0.0, "anthropomorphism": 0.0},
        temporal_baselines={"avg_daily_messages": 0, "avg_session_duration_min": 0},
        last_assessed_at=datetime.now(UTC),
    )
    db_session.add(profile)
    await db_session.commit()

    result = await db_session.execute(
        select(UserBehaviorProfile).where(UserBehaviorProfile.end_user_id == "test_user_1")
    )
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.risk_zone == "GREEN"
    assert fetched.danger_class_scores["self_harm"] == 0.0


@pytest.mark.asyncio
async def test_create_metrics_history(db_session):
    row = MetricsHistory(
        end_user_id="test_user_1",
        computed_at=datetime.now(UTC),
        period_type="5min",
        temporal_metrics={"session_count": 0, "total_messages": 0},
        danger_class_agg={"self_harm_avg": 0.0},
        behavioral_scores={"topic_concentration": 0.0},
        risk_zone="GREEN",
    )
    db_session.add(row)
    await db_session.commit()

    result = await db_session.execute(
        select(MetricsHistory).where(MetricsHistory.end_user_id == "test_user_1")
    )
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.period_type == "5min"
    assert fetched.temporal_metrics["session_count"] == 0


@pytest.mark.asyncio
async def test_create_behavioral_event(db_session):
    event = BehavioralEvent(
        end_user_id="test_user_1",
        detected_at=datetime.now(UTC),
        event_type="risk_zone_change",
        severity="YELLOW",
        details={"old_zone": "GREEN", "new_zone": "YELLOW", "trigger": "night_session_hours > 2"},
        acknowledged=False,
    )
    db_session.add(event)
    await db_session.commit()

    result = await db_session.execute(
        select(BehavioralEvent).where(BehavioralEvent.end_user_id == "test_user_1")
    )
    fetched = result.scalars().first()
    assert fetched is not None
    assert fetched.event_type == "risk_zone_change"
    assert fetched.details["trigger"] == "night_session_hours > 2"
    assert fetched.acknowledged is False
```

**Step 2: Run tests to verify they fail**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_behavioral_models.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'behavioral'`

**Step 3: Create the behavioral package**

Create `src/behavioral/__init__.py` (empty file).

Create `src/behavioral/models.py`:

```python
from sqlalchemy import Boolean, DateTime, Integer, JSON, String, text
from sqlalchemy.orm import mapped_column

from database.models import Base


class UserBehaviorProfile(Base):
    __tablename__ = "behavioral_user_profile"

    end_user_id = mapped_column(String, primary_key=True)
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))
    danger_class_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    temporal_baselines = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    last_assessed_at = mapped_column(DateTime(timezone=True), nullable=True)
    updated_at = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=text("CURRENT_TIMESTAMP"),
    )


class MetricsHistory(Base):
    __tablename__ = "behavioral_metrics_history"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(String, nullable=False, index=True)
    computed_at = mapped_column(DateTime(timezone=True), nullable=False)
    period_type = mapped_column(String, nullable=False)
    temporal_metrics = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    danger_class_agg = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    behavioral_scores = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    risk_zone = mapped_column(String, nullable=False, server_default=text("'GREEN'"))


class BehavioralEvent(Base):
    __tablename__ = "behavioral_events"

    id = mapped_column(Integer, primary_key=True, autoincrement=True)
    end_user_id = mapped_column(String, nullable=False, index=True)
    detected_at = mapped_column(DateTime(timezone=True), nullable=False)
    event_type = mapped_column(String, nullable=False)
    severity = mapped_column(String, nullable=False)
    details = mapped_column(JSON, nullable=False, server_default=text("'{}'"))
    acknowledged = mapped_column(Boolean, nullable=False, server_default=text("false"))
```

**Step 4: Update conftest to import behavioral models**

Add this import at the top of `tests/conftest.py` so that `Base.metadata.create_all` picks up the new tables:

```python
import behavioral.models  # noqa: F401 — register models with Base.metadata
```

**Step 5: Run tests to verify they pass**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_behavioral_models.py -v`
Expected: 3 passed

**Step 6: Commit**

```bash
cd ai-safety-mikhail
git add src/behavioral/__init__.py src/behavioral/models.py tests/test_behavioral_models.py tests/conftest.py
git commit -m "feat(behavioral): add UserBehaviorProfile, MetricsHistory, BehavioralEvent models"
```

---

## Task 3: Create the behavioral repository

**Files:**
- Create: `ai-safety-mikhail/src/behavioral/repository.py`
- Create: `ai-safety-mikhail/tests/test_behavioral_repository.py`

**Step 1: Write the failing test**

Create `tests/test_behavioral_repository.py`:

```python
import pytest
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from behavioral.repository import BehavioralRepository
from behavioral.models import UserBehaviorProfile, MetricsHistory, BehavioralEvent


@pytest.fixture
async def repo(db_engine):
    session_factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    return BehavioralRepository(session_factory)


@pytest.mark.asyncio
async def test_upsert_profile_creates_new(repo):
    await repo.upsert_profile(
        end_user_id="user_1",
        risk_zone="GREEN",
        danger_class_scores={"self_harm": 0.0},
        temporal_baselines={"avg_daily_messages": 0},
    )
    profile = await repo.get_profile("user_1")
    assert profile is not None
    assert profile.risk_zone == "GREEN"


@pytest.mark.asyncio
async def test_upsert_profile_updates_existing(repo):
    await repo.upsert_profile(
        end_user_id="user_1",
        risk_zone="GREEN",
        danger_class_scores={"self_harm": 0.0},
        temporal_baselines={},
    )
    await repo.upsert_profile(
        end_user_id="user_1",
        risk_zone="YELLOW",
        danger_class_scores={"self_harm": 0.3},
        temporal_baselines={},
    )
    profile = await repo.get_profile("user_1")
    assert profile.risk_zone == "YELLOW"
    assert profile.danger_class_scores["self_harm"] == 0.3


@pytest.mark.asyncio
async def test_add_metrics_history(repo):
    await repo.add_metrics_snapshot(
        end_user_id="user_1",
        period_type="5min",
        temporal_metrics={"total_messages": 5},
        danger_class_agg={"self_harm_avg": 0.1},
        behavioral_scores={"topic_concentration": 0.5},
        risk_zone="GREEN",
    )
    snapshots = await repo.get_recent_snapshots("user_1", limit=10)
    assert len(snapshots) == 1
    assert snapshots[0].temporal_metrics["total_messages"] == 5


@pytest.mark.asyncio
async def test_add_behavioral_event(repo):
    await repo.add_event(
        end_user_id="user_1",
        event_type="risk_zone_change",
        severity="YELLOW",
        details={"old_zone": "GREEN", "new_zone": "YELLOW"},
    )
    events = await repo.get_events("user_1", limit=10)
    assert len(events) == 1
    assert events[0].event_type == "risk_zone_change"
```

**Step 2: Run tests to verify they fail**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_behavioral_repository.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'behavioral.repository'`

**Step 3: Implement the repository**

Create `src/behavioral/repository.py`:

```python
from datetime import datetime, UTC

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from behavioral.models import UserBehaviorProfile, MetricsHistory, BehavioralEvent


class BehavioralRepository:
    def __init__(self, session_factory: async_sessionmaker):
        self._session_factory = session_factory

    async def get_profile(self, end_user_id: str) -> UserBehaviorProfile | None:
        async with self._session_factory() as session:
            result = await session.execute(
                select(UserBehaviorProfile).where(
                    UserBehaviorProfile.end_user_id == end_user_id
                )
            )
            return result.scalars().first()

    async def upsert_profile(
        self,
        end_user_id: str,
        risk_zone: str,
        danger_class_scores: dict,
        temporal_baselines: dict,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.execute(
                    select(UserBehaviorProfile).where(
                        UserBehaviorProfile.end_user_id == end_user_id
                    )
                )
                profile = existing.scalars().first()
                if profile is None:
                    profile = UserBehaviorProfile(end_user_id=end_user_id)
                    session.add(profile)
                profile.risk_zone = risk_zone
                profile.danger_class_scores = danger_class_scores
                profile.temporal_baselines = temporal_baselines
                profile.last_assessed_at = datetime.now(UTC)

    async def add_metrics_snapshot(
        self,
        end_user_id: str,
        period_type: str,
        temporal_metrics: dict,
        danger_class_agg: dict,
        behavioral_scores: dict,
        risk_zone: str,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                row = MetricsHistory(
                    end_user_id=end_user_id,
                    computed_at=datetime.now(UTC),
                    period_type=period_type,
                    temporal_metrics=temporal_metrics,
                    danger_class_agg=danger_class_agg,
                    behavioral_scores=behavioral_scores,
                    risk_zone=risk_zone,
                )
                session.add(row)

    async def get_recent_snapshots(
        self, end_user_id: str, limit: int = 10
    ) -> list[MetricsHistory]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(MetricsHistory)
                .where(MetricsHistory.end_user_id == end_user_id)
                .order_by(MetricsHistory.computed_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())

    async def add_event(
        self,
        end_user_id: str,
        event_type: str,
        severity: str,
        details: dict,
    ) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                event = BehavioralEvent(
                    end_user_id=end_user_id,
                    detected_at=datetime.now(UTC),
                    event_type=event_type,
                    severity=severity,
                    details=details,
                )
                session.add(event)

    async def get_events(
        self, end_user_id: str, limit: int = 10
    ) -> list[BehavioralEvent]:
        async with self._session_factory() as session:
            result = await session.execute(
                select(BehavioralEvent)
                .where(BehavioralEvent.end_user_id == end_user_id)
                .order_by(BehavioralEvent.detected_at.desc())
                .limit(limit)
            )
            return list(result.scalars().all())
```

**Step 4: Run tests to verify they pass**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_behavioral_repository.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
cd ai-safety-mikhail
git add src/behavioral/repository.py tests/test_behavioral_repository.py
git commit -m "feat(behavioral): add BehavioralRepository with upsert, snapshot, event methods"
```

---

## Task 4: Create the skeleton aggregator

**Files:**
- Create: `ai-safety-mikhail/src/behavioral/aggregator.py`
- Create: `ai-safety-mikhail/tests/test_aggregator_skeleton.py`

**Step 1: Write the failing test**

Create `tests/test_aggregator_skeleton.py`:

```python
import pytest
from datetime import datetime, UTC

from sqlalchemy.ext.asyncio import async_sessionmaker, AsyncSession

from behavioral.aggregator import BehavioralAggregator
from behavioral.repository import BehavioralRepository
from behavioral.models import UserBehaviorProfile


@pytest.fixture
async def repo(db_engine):
    session_factory = async_sessionmaker(bind=db_engine, class_=AsyncSession, expire_on_commit=False)
    return BehavioralRepository(session_factory)


@pytest.fixture
def aggregator(repo):
    return BehavioralAggregator(repo)


@pytest.mark.asyncio
async def test_run_for_user_creates_profile_and_snapshot(aggregator, repo):
    """Skeleton aggregator should create a GREEN profile and empty snapshot."""
    await aggregator.run_for_user("test_user_1")

    profile = await repo.get_profile("test_user_1")
    assert profile is not None
    assert profile.risk_zone == "GREEN"

    snapshots = await repo.get_recent_snapshots("test_user_1", limit=1)
    assert len(snapshots) == 1
    assert snapshots[0].period_type == "5min"
    assert snapshots[0].risk_zone == "GREEN"


@pytest.mark.asyncio
async def test_run_for_user_is_idempotent(aggregator, repo):
    """Running twice should not create duplicate profiles."""
    await aggregator.run_for_user("test_user_1")
    await aggregator.run_for_user("test_user_1")

    profile = await repo.get_profile("test_user_1")
    assert profile is not None

    snapshots = await repo.get_recent_snapshots("test_user_1", limit=10)
    assert len(snapshots) == 2  # two snapshots (one per run), but same profile
```

**Step 2: Run tests to verify they fail**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_aggregator_skeleton.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'behavioral.aggregator'`

**Step 3: Implement the skeleton aggregator**

Create `src/behavioral/aggregator.py`:

```python
import logging

from behavioral.repository import BehavioralRepository

logger = logging.getLogger("behavioral.aggregator")

# Empty defaults — Milestone 2-4 will replace these with real computations
EMPTY_TEMPORAL = {}
EMPTY_DANGER = {}
EMPTY_BEHAVIORAL = {}


class BehavioralAggregator:
    def __init__(self, repository: BehavioralRepository):
        self._repo = repository

    async def run_for_user(self, end_user_id: str) -> None:
        """Run the full aggregation pipeline for one user.

        Stages (skeleton — returns empty dicts, to be implemented in Milestones 2-4):
          1. Temporal metrics   — from SpendLogs
          2. Danger class agg   — from PredictTable
          3. Behavioral batch   — LLM analysis of message windows
          4. Risk zone engine   — rule-based classification
        """
        logger.info("Running aggregation for user=%s", end_user_id)

        # Stage 1: temporal metrics (Milestone 2)
        temporal = EMPTY_TEMPORAL

        # Stage 2: danger class aggregation (Milestone 3)
        danger = EMPTY_DANGER

        # Stage 3: behavioral batch LLM (Milestone 4)
        behavioral = EMPTY_BEHAVIORAL

        # Stage 4: risk zone engine (Milestone 5)
        risk_zone = "GREEN"

        # Write results
        await self._repo.add_metrics_snapshot(
            end_user_id=end_user_id,
            period_type="5min",
            temporal_metrics=temporal,
            danger_class_agg=danger,
            behavioral_scores=behavioral,
            risk_zone=risk_zone,
        )

        await self._repo.upsert_profile(
            end_user_id=end_user_id,
            risk_zone=risk_zone,
            danger_class_scores=danger,
            temporal_baselines=temporal,
        )

        logger.info("Aggregation complete for user=%s, zone=%s", end_user_id, risk_zone)
```

**Step 4: Run tests to verify they pass**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/test_aggregator_skeleton.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
cd ai-safety-mikhail
git add src/behavioral/aggregator.py tests/test_aggregator_skeleton.py
git commit -m "feat(behavioral): add skeleton aggregator with 4-stage pipeline stub"
```

---

## Task 5: Create the scheduler job and wire into main.py

**Files:**
- Create: `ai-safety-mikhail/src/behavioral/scheduler.py`
- Modify: `ai-safety-mikhail/src/main.py:30-41`

**Step 1: Create the behavioral scheduler**

Create `src/behavioral/scheduler.py`:

```python
import logging

from apscheduler.schedulers.asyncio import AsyncIOScheduler
from apscheduler.triggers.interval import IntervalTrigger
from sqlalchemy import select, distinct

from behavioral.aggregator import BehavioralAggregator
from behavioral.repository import BehavioralRepository
from database import Session
from database.models import LiteLLM_SpendLogs

logger = logging.getLogger("behavioral.scheduler")

AGGREGATION_INTERVAL_MINUTES = 5


async def _run_aggregation():
    """Find all end_users with recent activity and run aggregation for each."""
    repo = BehavioralRepository(Session)
    aggregator = BehavioralAggregator(repo)

    async with Session() as session:
        result = await session.execute(
            select(distinct(LiteLLM_SpendLogs.end_user)).where(
                LiteLLM_SpendLogs.end_user.isnot(None),
                LiteLLM_SpendLogs.end_user != "",
            )
        )
        end_users = [row[0] for row in result.all()]

    logger.info("Behavioral aggregation: found %d end_users", len(end_users))
    for end_user_id in end_users:
        try:
            await aggregator.run_for_user(end_user_id)
        except Exception:
            logger.exception("Aggregation failed for user=%s", end_user_id)


def register_behavioral_jobs(scheduler: AsyncIOScheduler) -> None:
    """Register the behavioral aggregation job on an existing scheduler."""
    scheduler.add_job(
        _run_aggregation,
        IntervalTrigger(minutes=AGGREGATION_INTERVAL_MINUTES),
        id="behavioral_aggregation",
        replace_existing=True,
        max_instances=1,
        coalesce=True,
        misfire_grace_time=300,
    )
    logger.info(
        "Behavioral aggregation job registered (every %d min)",
        AGGREGATION_INTERVAL_MINUTES,
    )
```

**Step 2: Wire into main.py**

In `src/main.py`, add the import at the top (after existing imports):

```python
from behavioral.scheduler import register_behavioral_jobs
```

Then modify the `wrapped_lifespan` function to call it:

Replace:
```python
@asynccontextmanager
async def wrapped_lifespan(app_):
    await create_all_schemas()  # must run before scheduler — it queries PredictTable
    scheduler = await start_langfuse_scheduler()
    try:
        async with old(app_) as _:
            yield
    finally:
        scheduler.shutdown(wait=False)
```

With:
```python
@asynccontextmanager
async def wrapped_lifespan(app_):
    await create_all_schemas()  # must run before scheduler — it queries PredictTable
    scheduler = await start_langfuse_scheduler()
    register_behavioral_jobs(scheduler)
    try:
        async with old(app_) as _:
            yield
    finally:
        scheduler.shutdown(wait=False)
```

**Step 3: Verify the app starts**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run python -c "from behavioral.scheduler import register_behavioral_jobs; print('import ok')"`
Expected: `import ok`

**Step 4: Run all tests to verify nothing is broken**

Run: `cd ai-safety-mikhail && PYTHONPATH=src uv run pytest tests/ -v`
Expected: all tests pass (7 total: 3 models + 4 repository + 2 aggregator = 9 — wait, that's 9)

**Step 5: Commit**

```bash
cd ai-safety-mikhail
git add src/behavioral/scheduler.py src/main.py
git commit -m "feat(behavioral): wire aggregator into APScheduler (every 5min)"
```

---

## Task 6: Verify end-to-end with running infrastructure

This task requires the Docker infrastructure to be running (`docker compose up -d` from repo root).

**Step 1: Start the proxy**

Run: `cd ai-safety-mikhail && source .env && PYTHONPATH=src uv run python src/main.py`

Watch the logs for:
- `Langfuse sessions scheduler started`
- `Behavioral aggregation job registered (every 5 min)`

**Step 2: Verify tables were created**

In another terminal, connect to PostgreSQL:

Run: `docker exec -it $(docker ps -qf "name=postgres") psql -U postgres -d litellm -c "\dt behavioral_*"`

Expected output should show 3 tables:
```
 behavioral_events
 behavioral_metrics_history
 behavioral_user_profile
```

**Step 3: Send a test message through Open WebUI to create a SpendLogs entry**

Open `http://localhost:30001` in browser, send any message to create at least one SpendLogs row with an `end_user`.

**Step 4: Wait 5 minutes for the aggregator to run, then check**

Run: `docker exec -it $(docker ps -qf "name=postgres") psql -U postgres -d litellm -c "SELECT end_user_id, risk_zone, last_assessed_at FROM behavioral_user_profile;"`

Expected: at least one row with `risk_zone = GREEN`

Run: `docker exec -it $(docker ps -qf "name=postgres") psql -U postgres -d litellm -c "SELECT id, end_user_id, period_type, risk_zone, computed_at FROM behavioral_metrics_history ORDER BY computed_at DESC LIMIT 5;"`

Expected: at least one row per user

**Step 5: Commit if any final adjustments were needed**

```bash
cd ai-safety-mikhail
git add -A
git commit -m "fix(behavioral): adjustments from end-to-end verification"
```

(Skip this step if no changes were needed.)

---

## Summary

| Task | What | Tests |
|------|------|-------|
| 1 | pytest infrastructure | 0 (setup only) |
| 2 | 3 SQLAlchemy models | 3 |
| 3 | BehavioralRepository | 4 |
| 4 | Skeleton aggregator | 2 |
| 5 | Scheduler + main.py wiring | import check |
| 6 | End-to-end verification | manual |

After Milestone 1, the pipeline runs but produces empty metrics and always returns GREEN. Milestones 2-5 replace the stubs with real computation.
