"""SQLAlchemy ORM schema for the three Phase-1 tables (plan.md §4.3).

``documents``     — canonical ``DocumentRecord`` rows.
``document_chunks``— text chunks (vector column lands Phase 3, not here).
``audit_log``     — strictly append-only ``AuditEvent`` rows (inserts only).

All datetime columns are timezone-naive and stored as UTC. JSON columns hold
plain dict/lists; SQLite stores them as TEXT via SQLAlchemy's JSON type.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
)
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column, relationship
from sqlalchemy.types import JSON


class Base(DeclarativeBase):
    """Declarative base for all regmon ORM tables."""


class DocumentRow(Base):
    """ORM row for the ``documents`` table (``DocumentRecord``)."""

    __tablename__ = "documents"

    doc_id: Mapped[str] = mapped_column(String, primary_key=True)
    source_id: Mapped[str] = mapped_column(String, nullable=False)
    url: Mapped[str] = mapped_column(String, nullable=False)
    title: Mapped[str] = mapped_column(String, nullable=False)
    body_text: Mapped[str] = mapped_column(Text, nullable=False)
    clean_text: Mapped[str] = mapped_column(Text, nullable=False)
    published_date: Mapped[datetime | None] = mapped_column(DateTime, nullable=True)
    reference_number: Mapped[str | None] = mapped_column(String, nullable=True)
    document_type: Mapped[str | None] = mapped_column(String, nullable=True)
    lang: Mapped[str | None] = mapped_column(String, nullable=True)
    jurisdiction: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    word_count: Mapped[int] = mapped_column(Integer, nullable=False)
    content_hash: Mapped[str] = mapped_column(String, nullable=False, index=True)
    simhash: Mapped[str | None] = mapped_column(String, nullable=True)
    embedding_ids: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)
    status: Mapped[str] = mapped_column(String, nullable=False, default="new")
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, nullable=False, default=datetime.utcnow, onupdate=datetime.utcnow
    )

    chunks: Mapped[list[DocumentChunkRow]] = relationship(
        back_populates="document",
        cascade="all, delete-orphan",
        order_by="DocumentChunkRow.ord",
    )


class DocumentChunkRow(Base):
    """ORM row for the ``document_chunks`` table (``DocumentChunk``)."""

    __tablename__ = "document_chunks"

    chunk_id: Mapped[str] = mapped_column(String, primary_key=True)
    doc_id: Mapped[str] = mapped_column(
        String, ForeignKey("documents.doc_id", ondelete="CASCADE"), nullable=False
    )
    ord: Mapped[int] = mapped_column(Integer, nullable=False)
    text: Mapped[str] = mapped_column(Text, nullable=False)
    char_count: Mapped[int] = mapped_column(Integer, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)

    document: Mapped[DocumentRow] = relationship(back_populates="chunks")


class AuditEventRow(Base):
    """ORM row for the strictly append-only ``audit_log`` table.

    No ``update``/``delete`` API is ever generated or exposed for this table;
    it receives inserts only. Re-inserting a duplicate ``event_id`` is rejected
    by the primary-key constraint.
    """

    __tablename__ = "audit_log"

    event_id: Mapped[str] = mapped_column(String, primary_key=True)
    ts: Mapped[datetime] = mapped_column(DateTime, nullable=False, default=datetime.utcnow)
    stage: Mapped[str] = mapped_column(String, nullable=False)
    actor: Mapped[str] = mapped_column(String, nullable=False)
    action: Mapped[str] = mapped_column(String, nullable=False)
    doc_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    run_id: Mapped[str | None] = mapped_column(String, nullable=True, index=True)
    metadata_: Mapped[dict] = mapped_column("metadata", JSON, nullable=False, default=dict)


__all__ = [
    "AuditEventRow",
    "Base",
    "DocumentChunkRow",
    "DocumentRow",
]
