"""Append-only ``AuditEvent`` writer + reader (plan.md §5.16).

Strictly insert-only: this class exposes only :meth:`append` and :meth:`list`.
There is deliberately no ``update`` / ``delete`` / ``remove`` method, and the
``audit_log`` table is only ever inserted into. Re-inserting the same
``event_id`` raises a clear ``ValueError`` (duplicate PK) rather than silently
overwriting — append-only integrity is non-negotiable.
"""

from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from regmon.db.schema import AuditEventRow
from regmon.models.enums import PipelineStage
from regmon.models.pipeline import AuditEvent


class AuditLog:
    """Async append-only writer + reader for :class:`AuditEvent`."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def append(self, event: AuditEvent) -> AuditEvent:
        """Insert ``event`` (insert-only) and return it with DB-defaulted ``ts``.

        Re-inserting the same ``event_id`` raises ``ValueError`` (duplicate PK)
        rather than overwriting.
        """
        async with self._session_factory() as session:
            row = AuditEventRow(
                event_id=event.event_id,
                ts=event.ts,
                stage=event.stage.value,
                actor=event.actor,
                action=event.action,
                doc_id=event.doc_id,
                run_id=event.run_id,
                metadata_=event.metadata,
            )
            session.add(row)
            try:
                await session.commit()
            except IntegrityError as exc:
                raise ValueError(
                    f"duplicate event_id {event.event_id!r} — audit_log is append-only"
                ) from exc
            return await self._fetch(session, event.event_id) or event

    async def list(
        self,
        run_id: str | None = None,
        stage: PipelineStage | None = None,
        limit: int = 100,
    ) -> list[AuditEvent]:
        """List audit events ordered by ``ts`` ascending, bounded by ``limit``."""
        async with self._session_factory() as session:
            stmt = select(AuditEventRow).order_by(AuditEventRow.ts)
            if run_id is not None:
                stmt = stmt.where(AuditEventRow.run_id == run_id)
            if stage is not None:
                stmt = stmt.where(AuditEventRow.stage == stage.value)
            stmt = stmt.limit(limit)
            result = await session.execute(stmt)
            return [_event_from_row(row) for row in result.scalars().all()]

    @staticmethod
    async def _fetch(session: AsyncSession, event_id: str) -> AuditEvent | None:
        row = await session.get(AuditEventRow, event_id)
        return _event_from_row(row) if row is not None else None


def _event_from_row(row: AuditEventRow) -> AuditEvent:
    """Round-trip an ORM :class:`AuditEventRow` back to an :class:`AuditEvent`."""
    return AuditEvent(
        event_id=row.event_id,
        ts=row.ts,
        stage=PipelineStage(row.stage),
        actor=row.actor,
        action=row.action,
        doc_id=row.doc_id,
        run_id=row.run_id,
        metadata=dict(row.metadata_ or {}),
    )


__all__ = ["AuditLog"]
