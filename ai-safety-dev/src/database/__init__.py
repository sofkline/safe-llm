import asyncio

from database.models import Base
from sqlalchemy import AsyncAdaptedQueuePool
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from config import settings

engine = create_async_engine(
    settings.database_url,
    poolclass=AsyncAdaptedQueuePool,
    pool_size=12,
    max_overflow=4,
    pool_pre_ping=True,
)

Session = async_sessionmaker(bind=engine, class_=AsyncSession, expire_on_commit=False)


async def create_all_schemas():
    async with engine.begin() as conn:
        await asyncio.sleep(1)
        await conn.run_sync(Base.metadata.create_all)
        await conn.commit()