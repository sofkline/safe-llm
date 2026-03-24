"""Shared test fixtures for behavioral monitoring tests."""

import os

# Set dummy env vars before any application imports, so that
# database.__init__ -> config.Settings() doesn't fail during test collection.
_TEST_ENV = {
    "DB_NAME": "test",
    "DB_USER": "test",
    "DB_PASSWORD": "test",
    "DB_HOST": "localhost",
    "DB_PORT": "5432",
    "LANGFUSE_SECRET_KEY": "test",
    "LANGFUSE_PUBLIC_KEY": "test",
    "LANGFUSE_API_HOST": "http://localhost",
    "API_BASE_URL": "http://localhost",
    "API_KEY": "test",
}
for k, v in _TEST_ENV.items():
    os.environ.setdefault(k, v)

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
    import behavioral.models  # noqa: F401 — register tables before create_all

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
