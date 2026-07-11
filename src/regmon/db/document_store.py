"""Async CRUD store for ``DocumentRecord`` (+ ``DocumentChunk``) (plan.md §5.16).

``upsert`` merges on ``doc_id`` collision: a re-processed document updates in
place rather than raising, and ``updated_at`` advances (``created_at`` stable).
Chunks for a ``doc_id`` are replaced wholesale on each upsert. Reads open a
fresh session each call, so returned models are detached and safe to use.
"""

from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from regmon.db.schema import DocumentChunkRow, DocumentRow
from regmon.models.documents import DocumentChunk, DocumentRecord
from regmon.models.enums import Jurisdiction


class DocumentStore:
    """Async persistence for canonical documents and their chunks."""

    def __init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None:
        self._session_factory = session_factory

    async def upsert(
        self,
        record: DocumentRecord,
        chunks: Sequence[DocumentChunk] = (),
    ) -> DocumentRecord:
        """Insert or update (merge) ``record`` and replace its ``chunks``.

        On ``doc_id`` collision the row is updated in place (``updated_at``
        advances) rather than raising. Chunk replacement is whole-set: prior
        chunks for this ``doc_id`` are deleted, then ``chunks`` are inserted.
        Returns the round-tripped ``DocumentRecord`` (DB-defaulted timestamps).
        """
        async with self._session_factory() as session:
            existing = await session.get(DocumentRow, record.doc_id)
            values = _row_values(record)
            if existing is None:
                session.add(DocumentRow(**values))
            else:
                for key, value in values.items():
                    setattr(existing, key, value)
            await session.execute(
                delete(DocumentChunkRow).where(DocumentChunkRow.doc_id == record.doc_id)
            )
            for chunk in chunks:
                session.add(
                    DocumentChunkRow(
                        chunk_id=chunk.chunk_id,
                        doc_id=record.doc_id,
                        ord=chunk.ord,
                        text=chunk.text,
                        char_count=chunk.char_count,
                    )
                )
            await session.commit()
            return await self.get(record.doc_id) or record

    async def get(self, doc_id: str) -> DocumentRecord | None:
        """Return the ``DocumentRecord`` for ``doc_id``, or ``None`` if absent."""
        async with self._session_factory() as session:
            row = await session.get(DocumentRow, doc_id)
            if row is None:
                return None
            return _record_from_row(row)

    async def exists_by_content_hash(self, content_hash: str) -> str | None:
        """Return the existing ``doc_id`` for ``content_hash``, or ``None``."""
        async with self._session_factory() as session:
            stmt = select(DocumentRow.doc_id).where(DocumentRow.content_hash == content_hash)
            result = await session.execute(stmt)
            return result.scalar_one_or_none()

    async def list(
        self,
        jurisdiction: Jurisdiction | None = None,
        limit: int = 100,
        offset: int = 0,
    ) -> list[DocumentRecord]:
        """List documents, optionally filtered by ``jurisdiction``."""
        async with self._session_factory() as session:
            stmt = select(DocumentRow)
            if jurisdiction is not None:
                stmt = stmt.where(DocumentRow.jurisdiction == jurisdiction.value)
            stmt = stmt.order_by(DocumentRow.created_at).limit(limit).offset(offset)
            result = await session.execute(stmt)
            return [_record_from_row(row) for row in result.scalars().all()]


def _row_values(record: DocumentRecord) -> dict[str, object]:
    """Map a :class:`DocumentRecord` to the ``DocumentRow`` column set."""
    return {
        "doc_id": record.doc_id,
        "source_id": record.source_id,
        "url": record.url,
        "title": record.title,
        "body_text": record.body_text,
        "clean_text": record.clean_text,
        "published_date": record.published_date,
        "reference_number": record.reference_number,
        "document_type": record.document_type.value if record.document_type else None,
        "lang": record.lang,
        "jurisdiction": record.jurisdiction.value if record.jurisdiction else None,
        "char_count": record.char_count,
        "word_count": record.word_count,
        "content_hash": record.content_hash,
        "simhash": record.simhash,
        "embedding_ids": record.embedding_ids,
        "status": record.status,
    }


def _record_from_row(row: DocumentRow) -> DocumentRecord:
    """Round-trip an ORM :class:`DocumentRow` back to a :class:`DocumentRecord`."""
    from regmon.models.enums import DocumentType

    return DocumentRecord(
        doc_id=row.doc_id,
        source_id=row.source_id,
        url=row.url,
        title=row.title,
        body_text=row.body_text,
        clean_text=row.clean_text,
        published_date=row.published_date,
        reference_number=row.reference_number,
        document_type=DocumentType(row.document_type) if row.document_type else None,
        lang=row.lang,
        jurisdiction=Jurisdiction(row.jurisdiction) if row.jurisdiction else None,
        char_count=row.char_count,
        word_count=row.word_count,
        content_hash=row.content_hash,
        simhash=row.simhash,
        embedding_ids=list(row.embedding_ids or []),
        status=row.status,
        created_at=row.created_at,
        updated_at=row.updated_at,
    )


__all__ = ["DocumentStore"]
