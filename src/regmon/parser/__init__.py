"""Parser package: HTML/PDF extraction and metadata parsing.

This module provides:
- HTMLParser: Extract title/body from HTML with boilerplate stripping
- PDFParser: Extract text and metadata from PDFs
- MetadataExtractor: Jurisdiction-specific date/ref/doc-type extraction
- ParserAgent: Orchestrator for parsing RawDocument -> ParsedDocument
- detect_content_type: Sniff HTML vs PDF from bytes or headers
"""

from __future__ import annotations

import asyncio
import hashlib
import logging
from datetime import datetime
from typing import Any, Literal

from regmon.models import Jurisdiction, RawDocument
from regmon.models.documents import ParsedDocument

# Re-export from submodules (at top to avoid E402)
from regmon.parser.html_parser import DEFAULT_STRIP_SELECTORS, HTMLParser
from regmon.parser.metadata import MetadataExtractor, extract_metadata
from regmon.parser.pdf_parser import PDFParser, parse_pdf

logger = logging.getLogger(__name__)


def detect_content_type(
    content_bytes: bytes, headers: dict[str, str] | None = None
) -> Literal["html", "pdf", "unknown"]:
    """
    Detect document content type from headers and/or magic bytes.

    Args:
        content_bytes: Raw document bytes.
        headers: Optional HTTP response headers.

    Returns:
        "html", "pdf", or "unknown".
    """
    # First check Content-Type header
    if headers:
        content_type = headers.get("Content-Type", "").lower()
        if "pdf" in content_type:
            return "pdf"
        if "html" in content_type or "xhtml" in content_type:
            return "html"
        if "xml" in content_type or "rss" in content_type or "atom" in content_type:
            return "html"  # Treat XML-like as HTML for parsing

    # Fallback to magic bytes
    if content_bytes.startswith(b"%PDF"):
        return "pdf"

    # Check for common HTML/XML starts
    head = content_bytes[:100].lower()
    if head.startswith(b"<!doctype html") or head.startswith(b"<html") or head.startswith(b"<?xml"):
        return "html"

    # RSS/Atom feeds often start with <rss or <feed
    if b"<rss" in head or b"<feed" in head or b"xmlns=" in head:
        return "html"

    return "unknown"


class ParserAgent:
    """
    Orchestrates HTML/PDF parsing and metadata extraction.

    Takes RawDocument objects from the crawler and produces ParsedDocument
    objects with extracted text and jurisdiction-specific metadata.
    """

    def __init__(
        self,
        html_parser: Any = None,
        pdf_parser: Any = None,
        metadata_extractor_factory: Any = None,
        max_concurrent: int = 10,
    ) -> None:
        """
        Initialize parser agent.

        Args:
            html_parser: HTMLParser instance (default: new with defaults).
            pdf_parser: PDFParser instance (default: new with defaults).
            metadata_extractor_factory: Callable(jurisdiction) -> MetadataExtractor.
            max_concurrent: Max concurrent parse operations.
        """
        # Lazy imports to avoid circular deps
        if html_parser is None:
            html_parser = HTMLParser()
        if pdf_parser is None:
            pdf_parser = PDFParser()

        self.html_parser = html_parser
        self.pdf_parser = pdf_parser
        self.metadata_extractor_factory = (
            metadata_extractor_factory or self._default_metadata_factory
        )
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _default_metadata_factory(self, jurisdiction: Jurisdiction) -> Any:
        """Default factory for MetadataExtractor."""
        return MetadataExtractor(jurisdiction)

    async def parse(
        self, raw_doc: RawDocument, jurisdiction: Jurisdiction
    ) -> ParsedDocument | None:
        """
        Parse a single RawDocument into a ParsedDocument.

        Args:
            raw_doc: RawDocument from crawler.
            jurisdiction: Jurisdiction for metadata extraction patterns.

        Returns:
            ParsedDocument or None if parsing fails.
        """
        async with self._semaphore:
            return await self._parse_one(raw_doc, jurisdiction)

    async def _parse_one(
        self, raw_doc: RawDocument, jurisdiction: Jurisdiction
    ) -> ParsedDocument | None:
        """Internal single-document parse with error handling."""
        try:
            # Detect content type
            content_type = detect_content_type(raw_doc.content_bytes, raw_doc.headers)

            # Extract text based on type
            if content_type == "pdf":
                title, body_text = await self._parse_pdf(raw_doc.content_bytes, raw_doc.url)
            else:
                title, body_text = await self._parse_html(
                    raw_doc.content_bytes, raw_doc.url, content_type
                )

            if not body_text.strip():
                logger.warning(
                    "Empty body text after parsing: %s (type=%s)", raw_doc.url, content_type
                )
                body_text = ""

            # Generate doc_id from URL + fetched_at for deterministic ID
            doc_id = self._generate_doc_id(raw_doc.url, raw_doc.fetched_at)

            # Extract jurisdiction-specific metadata
            full_text = f"{title}\n{body_text}" if title else body_text
            metadata_extractor = self.metadata_extractor_factory(jurisdiction)
            metadata = metadata_extractor.extract(full_text, raw_doc.url)

            parsed_doc = ParsedDocument(
                doc_id=doc_id,
                url=raw_doc.url,
                title=title or "Untitled",
                body_text=body_text,
                published_date=metadata.get("published_date"),
                reference_number=metadata.get("reference_number"),
                document_type=metadata.get("document_type"),
                lang=metadata.get("language"),
            )

            logger.debug("Parsed %s -> %s (%s chars)", raw_doc.url, doc_id, len(body_text))
            return parsed_doc

        except Exception as e:
            logger.exception("Failed to parse %s: %s", raw_doc.url, e)
            return None

    async def _parse_html(
        self, content_bytes: bytes, url: str, content_type: str
    ) -> tuple[str, str]:
        """Parse HTML content."""
        # Run CPU-bound BeautifulSoup in thread pool
        loop = asyncio.get_event_loop()
        return await loop.run_in_executor(None, self.html_parser.parse_bytes, content_bytes, url)

    async def _parse_pdf(self, content_bytes: bytes, url: str) -> tuple[str, str]:
        """Parse PDF content."""
        # Run CPU-bound PDF parsing in thread pool
        loop = asyncio.get_event_loop()
        full_text, pdf_metadata = await loop.run_in_executor(
            None, self.pdf_parser.parse, content_bytes
        )

        # Use PDF metadata title if available, otherwise fallback
        title = pdf_metadata.get("title", "") or url.split("/")[-1]
        return title, full_text

    def _generate_doc_id(self, url: str, fetched_at: datetime) -> str:
        """
        Generate deterministic document ID from URL and fetch timestamp.

        Uses SHA-256 truncated to 16 chars for readability.
        """
        key = f"{url}|{fetched_at.isoformat()}"
        return hashlib.sha256(key.encode()).hexdigest()[:16]

    async def parse_batch(
        self, raw_docs: list[RawDocument], jurisdictions: list[Jurisdiction]
    ) -> tuple[list[ParsedDocument], dict[str, Any]]:
        """
        Parse multiple documents concurrently.

        Args:
            raw_docs: List of RawDocument objects.
            jurisdictions: Corresponding jurisdictions for each document.

        Returns:
            Tuple of (list of successful ParsedDocument, stats dict).
        """
        if len(raw_docs) != len(jurisdictions):
            raise ValueError("raw_docs and jurisdictions must have same length")

        start_time = datetime.utcnow()
        tasks = [self.parse(doc, jur) for doc, jur in zip(raw_docs, jurisdictions, strict=True)]
        results: list[ParsedDocument | BaseException | None] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        parsed_docs: list[ParsedDocument] = []
        failed = 0
        errors = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                errors.append({"url": raw_docs[i].url, "error": str(result)})
                logger.error("Parse failed for %s: %s", raw_docs[i].url, result)
            elif result is None:
                failed += 1
                errors.append({"url": raw_docs[i].url, "error": "Parse returned None"})
            else:
                # result is narrowed to ParsedDocument here after isinstance/None checks
                parsed_docs.append(result)  # type: ignore[arg-type]

        duration = (datetime.utcnow() - start_time).total_seconds()

        stats = {
            "total": len(raw_docs),
            "parsed": len(parsed_docs),
            "failed": failed,
            "duration_seconds": duration,
            "errors": errors,
        }

        logger.info("Batch parse: %d parsed, %d failed (%.2fs)", len(parsed_docs), failed, duration)
        return parsed_docs, stats


__all__ = [
    "DEFAULT_STRIP_SELECTORS",
    "HTMLParser",
    "MetadataExtractor",
    "PDFParser",
    "ParserAgent",
    "detect_content_type",
    "extract_metadata",
    "parse_pdf",
]
