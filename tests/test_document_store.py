"""Unit tests for :class:`DocumentStore` — Phase-1 exit gate A.

Persist + retrieve a fully-populated ``DocumentRecord`` (plan.md §7 Phase 1).
"""

from __future__ import annotations

import asyncio
from datetime import datetime

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker

from regmon.db.document_store import DocumentStore
from regmon.db.schema import DocumentChunkRow
from regmon.models.documents import DocumentChunk, DocumentRecord
from regmon.models.enums import DocumentType, Jurisdiction


def make_record(doc_id: str = "doc-1", content_hash: str = "hash-1") -> DocumentRecord:
    return DocumentRecord(
        doc_id=doc_id,
        source_id="rbi",
        url="https://example.in/notification/1",
        title="RBI Notification on KYC",
        body_text="<html>...</html>",
        clean_text="RBI notification on KYC norms.",
        published_date=datetime(2026, 7, 11, 9, 30),
        reference_number="RBI/2026-27/123",
        document_type=DocumentType.NOTIFICATION,
        lang="en",
        jurisdiction=Jurisdiction.RBI,
        char_count=29,
        word_count=5,
        content_hash=content_hash,
    )


def make_chunks(doc_id: str) -> list[DocumentChunk]:
    return [
        DocumentChunk(chunk_id=f"{doc_id}-c0", doc_id=doc_id, ord=0, text="chunk0", char_count=6),
        DocumentChunk(chunk_id=f"{doc_id}-c1", doc_id=doc_id, ord=1, text="chunk1", char_count=6),
    ]


async def test_upsert_and_get_round_trip(sessions: async_sessionmaker) -> None:
    """Every field of a fully-populated record survives an upsert→get cycle."""
    store = DocumentStore(sessions)
    record = make_record()
    chunks = make_chunks(record.doc_id)

    persisted = await store.upsert(record, chunks)

    assert persisted.doc_id == "doc-1"
    assert persisted.source_id == "rbi"
    assert persisted.title == "RBI Notification on KYC"
    assert persisted.clean_text == "RBI notification on KYC norms."
    assert persisted.published_date == datetime(2026, 7, 11, 9, 30)
    assert persisted.reference_number == "RBI/2026-27/123"
    assert persisted.document_type is DocumentType.NOTIFICATION
    assert persisted.lang == "en"
    assert persisted.jurisdiction is Jurisdiction.RBI
    assert persisted.char_count == 29
    assert persisted.word_count == 5
    assert persisted.content_hash == "hash-1"
    assert persisted.simhash is None
    assert persisted.embedding_ids == []
    assert persisted.status == "new"
    # DB-defaulted timestamps are now populated.
    assert persisted.created_at is not None
    assert persisted.updated_at is not None

    fetched = await store.get("doc-1")
    assert fetched is not None
    assert fetched.title == persisted.title
    assert fetched.document_type is DocumentType.NOTIFICATION
    assert fetched.jurisdiction is Jurisdiction.RBI
    assert fetched.embedding_ids == []


async def test_get_missing_returns_none(sessions: async_sessionmaker) -> None:
    store = DocumentStore(sessions)
    assert await store.get("does-not-exist") is None


async def test_chunks_persisted(sessions: async_sessionmaker) -> None:
    """Upserted chunks land in document_chunks (verified via direct query)."""
    store = DocumentStore(sessions)
    await store.upsert(make_record(), make_chunks("doc-1"))

    async with sessions() as session:
        stmt = (
            select(DocumentChunkRow)
            .where(DocumentChunkRow.doc_id == "doc-1")
            .order_by(DocumentChunkRow.ord)
        )
        rows = (await session.execute(stmt)).scalars().all()

    assert [r.ord for r in rows] == [0, 1]
    assert [r.text for r in rows] == ["chunk0", "chunk1"]


async def test_chunks_replaced_on_reupsert(sessions: async_sessionmaker) -> None:
    """A second upsert with different chunks replaces the prior chunk set."""
    store = DocumentStore(sessions)
    rec = make_record()
    await store.upsert(rec, make_chunks(rec.doc_id))
    await store.upsert(
        rec,
        [DocumentChunk(chunk_id="doc-1-c9", doc_id=rec.doc_id, ord=0, text="only", char_count=4)],
    )

    async with sessions() as session:
        rows = (
            (
                await session.execute(
                    select(DocumentChunkRow).where(DocumentChunkRow.doc_id == rec.doc_id)
                )
            )
            .scalars()
            .all()
        )

    assert len(rows) == 1
    assert rows[0].chunk_id == "doc-1-c9"


async def test_upsert_same_doc_id_updates(
    sessions: async_sessionmaker,
) -> None:
    """Re-upserting the same ``doc_id`` updates rather than raising."""
    store = DocumentStore(sessions)
    rec = make_record()
    first = await store.upsert(rec, [])
    assert first is not None
    assert first.created_at is not None and first.updated_at is not None
    first_created, first_updated = first.created_at, first.updated_at

    # Change a field and space the two upserts so updated_at strictly advances.
    rec.title = "RBI Notification on KYC (Revised)"
    await asyncio.sleep(0.01)
    second = await store.upsert(rec, [])
    assert second is not None

    assert second.title == "RBI Notification on KYC (Revised)"
    assert second.created_at == first_created  # created_at stable
    assert second.updated_at > first_updated  # updated_at advanced


async def test_exists_by_content_hash(sessions: async_sessionmaker) -> None:
    """Hit returns the existing doc_id; miss returns None."""
    store = DocumentStore(sessions)
    await store.upsert(make_record(doc_id="doc-1", content_hash="abc"))

    assert await store.exists_by_content_hash("abc") == "doc-1"
    assert await store.exists_by_content_hash("nope") is None


def make_sebi_record() -> DocumentRecord:
    return DocumentRecord(
        doc_id="sebi-1",
        source_id="sebi",
        url="https://sebi.gov.in/x",
        title="SEBI Circular",
        body_text="x",
        clean_text="x",
        document_type=DocumentType.CIRCULAR,
        jurisdiction=Jurisdiction.SEBI,
        char_count=1,
        word_count=1,
        content_hash="h2",
    )


async def test_list_filters_and_paginates(sessions: async_sessionmaker) -> None:
    """``list`` honors jurisdiction filter plus limit/offset."""
    store = DocumentStore(sessions)
    await store.upsert(make_record(doc_id="rbi-1", content_hash="h1"), [])
    await store.upsert(make_sebi_record(), [])

    all_docs = await store.list()
    assert {d.doc_id for d in all_docs} == {"rbi-1", "sebi-1"}

    rbi_only = await store.list(jurisdiction=Jurisdiction.RBI)
    assert {d.doc_id for d in rbi_only} == {"rbi-1"}

    sebi_only = await store.list(jurisdiction=Jurisdiction.SEBI)
    assert {d.doc_id for d in sebi_only} == {"sebi-1"}

    # limit/offset over the unfiltered set.
    assert len(await store.list(limit=1)) <= 1
    first_page = await store.list(limit=1, offset=0)
    second_page = await store.list(limit=1, offset=1)
    assert {d.doc_id for d in first_page + second_page} == {"rbi-1", "sebi-1"}
