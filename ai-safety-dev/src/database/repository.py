from sqlalchemy import select

from database import Session
from database.models import LiteLLM_PredictTable


class PredictRepository:
    def __init__(self):
        self.session = Session()

    async def add(self, entity: LiteLLM_PredictTable) -> None:
        async with self.session as session:
            async with session.begin():
                session.add(entity)

    async def get(self, entity_id: int) -> LiteLLM_PredictTable:
        async with self.session as session:
            return await session.get(LiteLLM_PredictTable, entity_id)

    async def merge(self, entity: LiteLLM_PredictTable) -> None:
        """Merge entity in database like update"""
        async with self.session as session:
            async with session.begin():
                await session.merge(entity)
                await session.commit()

    async def get_all(self) -> list[LiteLLM_PredictTable]:
        async with self.session as session:
            query = select(LiteLLM_PredictTable)
            result = await session.execute(query)
            return result.scalars().all()

    async def get_by_session_id(self, session_id: str) -> LiteLLM_PredictTable | None:
        async with self.session as session:
            query = select(LiteLLM_PredictTable).where(LiteLLM_PredictTable.session_id == session_id)
            result = await session.execute(query)
            return result.scalars().first()

    async def last_time_recorded_by_all_users(self) -> list[LiteLLM_PredictTable]:
        async with self.session as session:
            query = (
                select(
                    LiteLLM_PredictTable.user_id,
                    LiteLLM_PredictTable.session_id,
                    LiteLLM_PredictTable.last_trace_id,
                )
                .distinct(LiteLLM_PredictTable.user_id)  # PostgreSQL DISTINCT ON (user_id)
                .order_by(
                    LiteLLM_PredictTable.user_id,
                    LiteLLM_PredictTable.last_trace_id.desc(),
                )
            )

            result = await session.execute(query)
            return result.all()