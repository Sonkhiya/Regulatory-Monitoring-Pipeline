"""PDF text extraction with metadata hints (TOC, page count, scanned detection)."""

from __future__ import annotations

import contextlib
import logging
from io import BytesIO
from typing import Any

from pypdf import PdfReader

logger = logging.getLogger(__name__)


class PDFParser:
    """Extracts text and metadata from PDF bytes."""

    def __init__(self, extract_toc: bool = True) -> None:
        """
        Initialize PDF parser.

        Args:
            extract_toc: If True, attempt to extract table of contents entries.
        """
        self.extract_toc = extract_toc

    def parse(self, pdf_bytes: bytes) -> tuple[str, dict[str, Any]]:
        """
        Parse PDF and extract text + metadata.

        Args:
            pdf_bytes: Raw PDF content.

        Returns:
            Tuple of (full_text, metadata_dict).
            metadata_dict may contain:
            - page_count: int
            - toc_entries: list[dict] (if extract_toc=True)
            - is_scanned: bool (heuristic: no extractable text)
            - title: str (from PDF metadata)
            - author: str (from PDF metadata)
            - subject: str (from PDF metadata)
            - creator: str (from PDF metadata)
            - producer: str (from PDF metadata)
            - creation_date: str (from PDF metadata)
            - modification_date: str (from PDF metadata)
        """
        if not pdf_bytes:
            logger.warning("Empty PDF bytes provided")
            return "", {"page_count": 0, "is_scanned": True, "toc_entries": []}

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
        except Exception as e:
            logger.warning("Failed to parse PDF: %s", e)
            return "", {"page_count": 0, "is_scanned": True, "toc_entries": [], "error": str(e)}

        page_count = len(reader.pages)
        logger.debug("PDF has %d pages", page_count)

        # Extract text from all pages
        texts = []
        for i, page in enumerate(reader.pages):
            try:
                page_text = page.extract_text()
                if page_text:
                    texts.append(page_text)
                else:
                    logger.debug("Page %d has no extractable text", i + 1)
            except Exception as e:
                logger.warning("Failed to extract text from page %d: %s", i + 1, e)

        full_text = "\n\n".join(texts)

        # Check if scanned (no extractable text)
        is_scanned = len(full_text.strip()) == 0
        if is_scanned:
            logger.warning("PDF appears to be scanned/image-only (no extractable text)")

        metadata: dict[str, Any] = {
            "page_count": page_count,
            "is_scanned": is_scanned,
            "toc_entries": [],
            "title": "",
            "author": "",
            "subject": "",
            "creator": "",
            "producer": "",
            "creation_date": "",
            "modification_date": "",
        }

        # Extract PDF metadata
        if reader.metadata:
            pdf_meta = reader.metadata
            metadata.update(
                {
                    "title": pdf_meta.title or "",
                    "author": pdf_meta.author or "",
                    "subject": pdf_meta.subject or "",
                    "creator": pdf_meta.creator or "",
                    "producer": pdf_meta.producer or "",
                    "creation_date": (
                        str(pdf_meta.creation_date) if pdf_meta.creation_date else ""
                    ),
                    "modification_date": (
                        str(pdf_meta.modification_date) if pdf_meta.modification_date else ""
                    ),
                }
            )

        # Extract TOC/outline if requested
        if self.extract_toc and reader.outline:
            toc_entries = self._extract_toc(reader.outline)
            metadata["toc_entries"] = toc_entries
            logger.debug("Extracted %d TOC entries", len(toc_entries))

        return full_text, metadata

    def _extract_toc(self, outline: list[Any], level: int = 0) -> list[dict[str, Any]]:
        """Recursively extract table of contents from PDF outline."""
        entries = []
        for item in outline:
            if isinstance(item, list):
                # Nested outline items
                entries.extend(self._extract_toc(item, level + 1))
            elif hasattr(item, "title"):
                # Outline item (destination)
                entry = {
                    "title": item.title,
                    "level": level,
                }
                # Try to get page number
                if hasattr(item, "page") and item.page is not None:
                    with contextlib.suppress(Exception):
                        entry["page"] = self._get_page_number(item.page)
                entries.append(entry)
        return entries

    def _get_page_number(self, page_obj: Any) -> int | None:
        """Try to get page number from page object."""
        # This is a bit of a hack since pypdf doesn't expose direct page numbers
        # from outline items easily. We return None if we can't determine it.
        return None

    def extract_first_page_text(self, pdf_bytes: bytes, max_chars: int = 5000) -> str:
        """
        Extract text from first page only (useful for quick preview/metadata).

        Args:
            pdf_bytes: Raw PDF content.
            max_chars: Maximum characters to return.

        Returns:
            Text from first page (truncated).
        """
        if not pdf_bytes:
            return ""

        try:
            reader = PdfReader(BytesIO(pdf_bytes))
            if len(reader.pages) > 0:
                text = reader.pages[0].extract_text()
                return text[:max_chars] if text else ""
        except Exception as e:
            logger.warning("Failed to extract first page text: %s", e)
        return ""


def parse_pdf(pdf_bytes: bytes, extract_toc: bool = True) -> tuple[str, dict[str, Any]]:
    """
    Convenience function for one-off PDF parsing.

    Args:
        pdf_bytes: Raw PDF content.
        extract_toc: Whether to extract table of contents.

    Returns:
        Tuple of (full_text, metadata_dict).
    """
    parser = PDFParser(extract_toc=extract_toc)
    return parser.parse(pdf_bytes)
