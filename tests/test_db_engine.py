"""Unit tests for the async engine factory and ``init_db`` (plan.md §5.16)."""

from __future__ import annotations

import pytest
from sqlalchemy import inspect
from sqlalchemy.ext.asyncio import AsyncEngine

from regmon.config import Settings
from regmon.db.engine import create_async_engine


async def test_create_async_engine_returns_engine() -> None:
    eng = create_async_engine(Settings(db_url="sqlite+aiosqlite:///:memory:"))
    assert isinstance(eng, AsyncEngine)
    await eng.dispose()


async def test_init_db_creates_three_tables(engine: AsyncEngine) -> None:
    """``init_db`` creates exactly documents, document_chunks, audit_log."""

    def names(conn: object) -> list[str]:
        return inspect(conn).get_table_names()

    async with engine.connect() as conn:
        tables = await conn.run_sync(names)

    assert set(tables) >= {"documents", "document_chunks", "audit_log"}
    assert set(tables) <= {"documents", "document_chunks", "audit_log"}


def test_sync_sqlite_url_rejected() -> None:
    """A sync ``sqlite:///`` URL raises a clear ``ValueError``."""
    settings = Settings(db_url="sqlite:///regmon.db")
    with pytest.raises(ValueError, match="sync sqlite URL not supported"):
        create_async_engine(settings)
