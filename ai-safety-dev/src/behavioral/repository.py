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
            # naive datetime: MetricsHistory.computed_at is TIMESTAMP WITHOUT TIME ZONE
            cutoff = datetime.utcnow().replace(
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
        """Upsert: обновляем если запись за этот день уже есть, иначе вставляем."""
        async with self._session_factory() as session:
            async with session.begin():
                existing = await session.execute(
                    select(DailySummary).where(
                        and_(
                            DailySummary.end_user_id == summary.end_user_id,
                            DailySummary.summary_date == summary.summary_date,
                        )
                    )
                )
                existing_row = existing.scalars().first()
                if existing_row:
                    existing_row.key_topics = summary.key_topics
                    existing_row.life_events = summary.life_events
                    existing_row.emotional_tone = summary.emotional_tone
                    existing_row.ai_relationship_markers = summary.ai_relationship_markers
                    existing_row.notable_quotes = summary.notable_quotes
                    existing_row.operator_note = summary.operator_note
                    existing_row.is_notable = summary.is_notable
                else:
                    session.add(summary)

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
            cutoff = datetime.utcnow() - timedelta(days=days)
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
