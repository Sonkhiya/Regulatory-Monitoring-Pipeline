"""Normalization: encoding repair, boilerplate stripping, and language detection (Phase 2b)."""

from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, cast

from regmon.models import ParsedDocument
from regmon.models.documents import NormalizedDocument
from regmon.normalize.boilerplate import BoilerplateStripper, strip_boilerplate

# Re-export from submodules
from regmon.normalize.encoding_repair import EncodingRepair, repair_encoding
from regmon.normalize.language import LanguageDetector, detect_language

logger = logging.getLogger(__name__)


class NormalizerAgent:
    """Orchestrates normalization: encoding repair → boilerplate strip → language detect → stats."""

    def __init__(
        self,
        encoding_repair: EncodingRepair | None = None,
        boilerplate_stripper: BoilerplateStripper | None = None,
        language_detector: LanguageDetector | None = None,
        max_concurrent: int = 10,
    ) -> None:
        """
        Initialize normalizer agent.

        Args:
            encoding_repair: EncodingRepair instance (default: new with defaults).
            boilerplate_stripper: BoilerplateStripper instance (default: new with defaults).
            language_detector: LanguageDetector instance (default: new with defaults).
            max_concurrent: Max concurrent normalization operations.
        """
        self.encoding_repair = encoding_repair or EncodingRepair()
        self.boilerplate_stripper = boilerplate_stripper or BoilerplateStripper()
        self.language_detector = language_detector or LanguageDetector()
        self._semaphore = asyncio.Semaphore(max_concurrent)

    def _derive_site_key(self, parsed_doc: ParsedDocument) -> str:
        """Derive site key from URL for boilerplate tracking."""
        from urllib.parse import urlparse

        try:
            parsed = urlparse(parsed_doc.url)
            domain = parsed.netloc.lower()
            # Remove www. prefix
            if domain.startswith("www."):
                domain = domain[4:]
            return domain
        except Exception:
            return "default"

    async def normalize(
        self,
        parsed_doc: ParsedDocument,
        site_key: str | None = None,
    ) -> NormalizedDocument | None:
        """
        Normalize a single ParsedDocument.

        Args:
            parsed_doc: ParsedDocument from parser.
            site_key: Optional site key for boilerplate tracking (derived from URL if not provided).

        Returns:
            NormalizedDocument or None if normalization fails.
        """
        async with self._semaphore:
            return await self._normalize_one(parsed_doc, site_key)

    async def _normalize_one(
        self,
        parsed_doc: ParsedDocument,
        site_key: str | None = None,
    ) -> NormalizedDocument | None:
        """Internal single-document normalization with error handling."""
        try:
            site_key = site_key or self._derive_site_key(parsed_doc)

            # Handle empty body text
            body_text = parsed_doc.body_text or ""
            if body_text == "":
                logger.warning(
                    "Empty body text for doc %s (%s), returning minimal NormalizedDocument",
                    parsed_doc.doc_id,
                    parsed_doc.url,
                )
                language, confidence = self.fallback_language(body_text)
                return NormalizedDocument(
                    doc_id=parsed_doc.doc_id,
                    url=parsed_doc.url,
                    title=parsed_doc.title,
                    body_text=body_text,
                    published_date=parsed_doc.published_date,
                    reference_number=parsed_doc.reference_number,
                    document_type=parsed_doc.document_type,
                    lang=parsed_doc.lang,
                    clean_text="",
                    language=language,
                    char_count=0,
                    word_count=0,
                )

            # Step 1: Encoding repair
            clean_text, repair_info = self.encoding_repair.repair(body_text)
            if repair_info.get("ftfy_applied"):
                logger.debug("Encoding repair applied for %s", parsed_doc.doc_id)

            # Step 2: Boilerplate stripping
            clean_text, strip_info = self.boilerplate_stripper.strip(clean_text, site_key)
            if strip_info.get("boilerplate_removed"):
                logger.debug(
                    "Boilerplate stripped for %s: %d chars removed",
                    parsed_doc.doc_id,
                    strip_info.get("chars_removed", 0),
                )

            # Step 3: Language detection
            language, confidence = self.language_detector.detect(clean_text)
            if confidence < 0.5:
                logger.debug(
                    "Low confidence language detection for %s: %s (%.2f)",
                    parsed_doc.doc_id,
                    language,
                    confidence,
                )

            # Step 4: Compute token stats
            char_count = len(clean_text)
            word_count = len(clean_text.split())

            normalized_doc = NormalizedDocument(
                doc_id=parsed_doc.doc_id,
                url=parsed_doc.url,
                title=parsed_doc.title,
                body_text=body_text,
                published_date=parsed_doc.published_date,
                reference_number=parsed_doc.reference_number,
                document_type=parsed_doc.document_type,
                lang=parsed_doc.lang,
                clean_text=clean_text,
                language=language,
                char_count=char_count,
                word_count=word_count,
            )

            logger.debug(
                "Normalized %s: lang=%s, chars=%d, words=%d",
                parsed_doc.doc_id,
                language,
                char_count,
                word_count,
            )

            return normalized_doc

        except Exception as e:
            logger.exception("Failed to normalize %s: %s", parsed_doc.doc_id, e)
            return None

    @staticmethod
    def fallback_language(text: str) -> tuple[str, float]:
        """Get fallback language (used for empty text)."""
        detector = LanguageDetector()
        return detector.detect(text)

    async def normalize_batch(
        self,
        parsed_docs: list[ParsedDocument],
        site_keys: list[str] | None = None,
    ) -> tuple[list[NormalizedDocument], dict[str, Any]]:
        """
        Normalize multiple documents concurrently.

        Args:
            parsed_docs: List of ParsedDocument objects.
            site_keys: Optional list of site keys (same length as parsed_docs).

        Returns:
            Tuple of (list of successful NormalizedDocument, stats dict).
        """
        if site_keys is None:
            site_keys = [self._derive_site_key(doc) for doc in parsed_docs]
        elif len(parsed_docs) != len(site_keys):
            raise ValueError("parsed_docs and site_keys must have same length")

        start_time = datetime.utcnow()
        logger.info("Starting batch normalization of %d documents", len(parsed_docs))

        tasks = [
            self.normalize(doc, site_key)
            for doc, site_key in zip(parsed_docs, site_keys, strict=True)
        ]
        results: list[NormalizedDocument | BaseException | None] = await asyncio.gather(
            *tasks, return_exceptions=True
        )

        normalized_docs: list[NormalizedDocument] = []
        failed = 0
        errors = []

        for i, result in enumerate(results):
            if isinstance(result, Exception):
                failed += 1
                errors.append({"doc_id": parsed_docs[i].doc_id, "error": str(result)})
                logger.error("Normalization failed for %s: %s", parsed_docs[i].doc_id, result)
            elif result is None:
                failed += 1
                errors.append(
                    {
                        "doc_id": parsed_docs[i].doc_id,
                        "error": "Normalization returned None",
                    }
                )
            else:
                normalized_docs.append(cast(NormalizedDocument, result))

        duration = (datetime.utcnow() - start_time).total_seconds()

        stats = {
            "total": len(parsed_docs),
            "normalized": len(normalized_docs),
            "failed": failed,
            "duration_seconds": duration,
            "errors": errors,
        }

        logger.info(
            "Batch normalization complete: %d normalized, %d failed (%.2fs)",
            len(normalized_docs),
            failed,
            duration,
        )

        return normalized_docs, stats


def normalize_document(parsed_doc: ParsedDocument, site_key: str = "default") -> NormalizedDocument:
    """
    Sync convenience function for one-off normalization.

    Note: This creates default component instances each call.
    For batch processing, use NormalizerAgent.
    """
    agent = NormalizerAgent()
    # Run sync by using asyncio.run for the single document
    import asyncio

    return asyncio.run(agent.normalize(parsed_doc, site_key)) or NormalizedDocument(
        doc_id=parsed_doc.doc_id,
        url=parsed_doc.url,
        title=parsed_doc.title,
        body_text=parsed_doc.body_text,
        published_date=parsed_doc.published_date,
        reference_number=parsed_doc.reference_number,
        document_type=parsed_doc.document_type,
        lang=parsed_doc.lang,
        clean_text="",
        language="en",
        char_count=0,
        word_count=0,
    )


__all__ = [
    "BoilerplateStripper",
    "EncodingRepair",
    "LanguageDetector",
    "NormalizerAgent",
    "detect_language",
    "normalize_document",
    "repair_encoding",
    "strip_boilerplate",
]
