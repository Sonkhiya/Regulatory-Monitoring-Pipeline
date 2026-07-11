"""Async SQLAlchemy engine factory, session factory, and schema bootstrap.

All DB I/O in regmon is fully async (``create_async_engine`` + ``AsyncSession``).
A sync-only ``sqlite:///`` URL is rejected at factory time with a clear
``ValueError`` — async semantics are non-negotiable (plan.md §7 Phase 1).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.ext.asyncio import (
    create_async_engine as _sa_create_async_engine,
)
from sqlalchemy.pool import StaticPool

from regmon.config import Settings
from regmon.db.schema import Base


def create_async_engine(settings: Settings | None = None) -> AsyncEngine:
    """Build an :class:`AsyncEngine` from ``Settings.db_url``.

    Rejects a sync ``sqlite:///…`` URL (missing the ``+aiosqlite`` driver) with
    a clear ``ValueError`` rather than failing opaquely at first query. In-memory
    SQLite (``sqlite+aiosqlite:///:memory:``) uses a :class:`StaticPool` so every
    connection shares the same DB — otherwise each connection would get a fresh,
    empty database and ``init_db``'s tables would be invisible to later sessions.
    """
    if settings is None:
        settings = Settings()
    url = settings.db_url

    if url.startswith("sqlite://") and not url.startswith("sqlite+aiosqlite"):
        raise ValueError(
            f"sync sqlite URL not supported: {url!r} — "
            "use 'sqlite+aiosqlite:///...' (see REGMON_DB_URL in .env.example)"
        )

    kwargs: dict[str, object] = {}
    if url.startswith("sqlite"):
        kwargs["connect_args"] = {"check_same_thread": False}
        if ":memory:" in url:
            kwargs["poolclass"] = StaticPool
    return _sa_create_async_engine(url, **kwargs)


def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    """Return an :class:`async_sessionmaker` bound to ``engine``."""
    return async_sessionmaker(engine, expire_on_commit=False)


async def init_db(engine: AsyncEngine) -> None:
    """Create all Phase-1 tables if absent (``Base.metadata.create_all``)."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)


__all__ = ["create_async_engine", "init_db", "session_factory"]
