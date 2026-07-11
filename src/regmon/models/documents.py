"""Document-chain Pydantic models (plan.md §4.2).

The crawl → parse → normalize pipeline produces successively richer document
models, terminating in ``DocumentRecord`` — the DB-backed canonical form
persisted to the ``documents`` table. ``DocumentChunk`` mirrors the
``document_chunks`` table that Phase 3's indexer extends with a vector column.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from regmon.models.enums import DocumentType, Jurisdiction


class RegulatorySource(BaseModel):
    """A configured regulatory source (a crawler adapter target)."""

    id: str
    jurisdiction: Jurisdiction
    name: str
    listing_url: str | None = None
    feed_url: str | None = None
    adapter: str
    crawl_policy: dict[str, Any] = Field(default_factory=dict)


class RawDocument(BaseModel):
    """Raw fetched bytes + response metadata from a source adapter."""

    source_id: str
    url: str
    fetched_at: datetime
    http_status: int
    content_bytes: bytes
    headers: dict[str, str] = Field(default_factory=dict)
    etag: str | None = None
    last_modified: str | None = None


class ParsedDocument(BaseModel):
    """Parsed text + extracted metadata from a ``RawDocument``."""

    doc_id: str
    url: str
    title: str
    body_text: str
    published_date: datetime | None = None
    reference_number: str | None = None
    document_type: DocumentType | None = None
    lang: str | None = None


class NormalizedDocument(ParsedDocument):
    """Cleaned/normalized document with token statistics."""

    clean_text: str
    language: str
    char_count: int
    word_count: int


class DocumentChunk(BaseModel):
    """A chunk of a ``DocumentRecord`` (mirrors the ``document_chunks`` table).

    The vector/embedding column is intentionally absent — it lands in Phase 3
    with the indexer. ``from_attributes`` lets the store round-trip ORM rows.
    """

    model_config = ConfigDict(from_attributes=True)

    chunk_id: str
    doc_id: str
    ord: int
    text: str
    char_count: int


class DocumentRecord(BaseModel):
    """Canonical DB-backed document form (persisted to the ``documents`` table).

    ``simhash`` is populated only in Phase 3; ``embedding_ids`` is empty in
    Phase 1 and populated by the Phase 3 indexer. ``jurisdiction`` is carried
    here so ``DocumentStore.list(jurisdiction=...)`` can filter without a
    sources join (no sources table exists until later phases). ``created_at``/
    ``updated_at`` are DB-defaulted; they are ``None`` until persisted.
    """

    model_config = ConfigDict(from_attributes=True)

    doc_id: str
    source_id: str
    url: str
    title: str
    body_text: str
    clean_text: str
    published_date: datetime | None = None
    reference_number: str | None = None
    document_type: DocumentType | None = None
    lang: str | None = None
    jurisdiction: Jurisdiction | None = None
    char_count: int
    word_count: int
    content_hash: str
    simhash: str | None = None
    embedding_ids: list[str] = Field(default_factory=list)
    status: str = "new"
    created_at: datetime | None = None
    updated_at: datetime | None = None


__all__ = [
    "DocumentChunk",
    "DocumentRecord",
    "NormalizedDocument",
    "ParsedDocument",
    "RawDocument",
    "RegulatorySource",
]
