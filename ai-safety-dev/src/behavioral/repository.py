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
        self._session_factory = Session

    # --- UserBehaviorProfile ---

    async def get_profile(self, end_user_id: str) -> UserBehaviorProfile | None:
        async with self._session_factory() as session:
            return await session.get(UserBehaviorProfile, end_user_id)

    async def upsert_profile(self, profile: UserBehaviorProfile) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                await session.merge(profile)

    async def get_risk_zone(self, end_user_id: str) -> str | None:
        """Fast lookup for middleware — returns risk_zone or None if no profile."""
        async with self._session_factory() as session:
            query = (
                select(UserBehaviorProfile.risk_zone)
                .where(UserBehaviorProfile.end_user_id == end_user_id)
            )
            result = await session.execute(query)
            row = result.scalar_one_or_none()
            return row

    # --- MetricsHistory ---

    async def add_metrics_history(self, entry: MetricsHistory) -> None:
        async with self._session_factory() as session:
            async with session.begin():
                session.add(entry)

    async def get_recent_metrics(
        self, end_user_id: str, days: int = 7
    ) -> list[MetricsHistory]:
        async with self._session_factory() as session:
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
        async with self._session_factory() as session:
            async with session.begin():
                await session.merge(summary)

    async def get_notable_calendar(
        self, end_user_id: str, limit: int = 14
    ) -> list[DailySummary]:
        """Fetch notable days for Stage 3 calendar context."""
        async with self._session_factory() as session:
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
        async with self._session_factory() as session:
            async with session.begin():
                session.add(event)

    async def get_recent_events(
        self, end_user_id: str, days: int = 7
    ) -> list[BehavioralEvent]:
        async with self._session_factory() as session:
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
