"""Shared pytest fixtures for the regmon test suite (Phase 1).

In-memory SQLite (``sqlite+aiosqlite:///:memory:``) is handled by the engine
factory itself, which swaps in a :class:`StaticPool` so every connection shares
one database — that lets ``init_db`` (DDL on a begin connection) and the later
store/audit-log sessions all see the same tables.
"""

from __future__ import annotations

import pytest
import pytest_asyncio
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker

from regmon.config import Settings
from regmon.db.engine import create_async_engine, init_db, session_factory

MEMORY_URL = "sqlite+aiosqlite:///:memory:"


@pytest.fixture
def db_settings(monkeypatch: pytest.MonkeyPatch) -> Settings:
    """Settings pointing at the in-memory SQLite URL."""
    monkeypatch.setenv("REGMON_DB_URL", MEMORY_URL)
    # ``get_settings`` is lru_cached; clear it so the env override takes effect.
    from regmon.config import settings as settings_module

    settings_module.get_settings.cache_clear()
    return Settings(db_url=MEMORY_URL)


@pytest_asyncio.fixture
async def engine(db_settings: Settings) -> AsyncEngine:
    """A shared in-memory AsyncEngine with tables initialized."""
    eng = create_async_engine(db_settings)
    await init_db(eng)
    yield eng
    await eng.dispose()


@pytest_asyncio.fixture
async def sessions(engine: AsyncEngine) -> async_sessionmaker:
    """A session factory bound to the shared in-memory engine."""
    return session_factory(engine)
