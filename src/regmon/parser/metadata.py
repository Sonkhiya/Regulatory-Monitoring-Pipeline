"""Jurisdiction-specific metadata extraction (dates, reference numbers, doc types)."""

from __future__ import annotations

import logging
import re
from datetime import datetime
from pathlib import Path
from typing import Any

import dateparser
import yaml

from regmon.models.enums import DocumentType, Jurisdiction

logger = logging.getLogger(__name__)

# Default patterns config path
DEFAULT_PATTERNS_PATH = (
    Path(__file__).parent.parent.parent.parent / "config" / "parser_patterns.yaml"
)


class MetadataExtractor:
    """Extracts jurisdiction-specific metadata from parsed document text."""

    def __init__(self, jurisdiction: Jurisdiction, patterns_path: Path | None = None) -> None:
        """
        Initialize metadata extractor for a jurisdiction.

        Args:
            jurisdiction: Jurisdiction enum value.
            patterns_path: Path to YAML pattern config. Defaults to config/parser_patterns.yaml.
        """
        self.jurisdiction = jurisdiction
        self.patterns_path = patterns_path or DEFAULT_PATTERNS_PATH
        self._patterns: dict[str, Any] = {}
        self._load_patterns()

    def _load_patterns(self) -> None:
        """Load patterns from YAML config."""
        if not self.patterns_path.exists():
            logger.warning("Patterns file not found: %s", self.patterns_path)
            self._patterns = {}
            return

        try:
            with self.patterns_path.open("r", encoding="utf-8") as f:
                config = yaml.safe_load(f) or {}
            self._patterns = config.get(self.jurisdiction.value, {})
            if not self._patterns:
                logger.warning("No patterns for jurisdiction %s in config", self.jurisdiction.value)
        except Exception as e:
            logger.warning("Failed to load patterns from %s: %s", self.patterns_path, e)
            self._patterns = {}

    def extract(self, text: str, url: str) -> dict[str, Any]:
        """
        Extract metadata from document text and URL.

        Args:
            text: Full document text (title + body).
            url: Source URL (used for reference patterns).

        Returns:
            Dict with keys: published_date, reference_number, document_type, language.
        """
        # Search in title + first 3000 chars of body (where metadata usually appears)
        search_text = text[:3000] if len(text) > 3000 else text

        result = {
            "published_date": self._extract_date(search_text),
            "reference_number": self._extract_reference(search_text, url),
            "document_type": self._extract_document_type(search_text, url),
            "language": self._detect_language(text),
        }
        return result

    def _extract_date(self, text: str) -> datetime | None:
        """Extract publication date from text."""
        date_patterns = self._patterns.get("date_patterns", [])

        for pattern_info in date_patterns:
            pattern = pattern_info.get("pattern")
            fmt = pattern_info.get("format")
            flags = pattern_info.get("flags", 0)

            if not pattern:
                continue

            matches = re.findall(pattern, text, flags)
            for match in matches:
                # match can be string or tuple from capturing groups
                if isinstance(match, tuple):
                    # Take first non-empty group
                    for m in match:
                        if m:
                            match = m
                            break
                    else:
                        continue

                try:
                    if fmt:
                        return datetime.strptime(match, fmt)
                    # Let dateparser handle it
                    parsed = dateparser.parse(
                        match,
                        settings=self._patterns.get(
                            "dateparser_settings", {"DEFAULT_LANGUAGES": ["en"]}
                        ),
                    )
                    if parsed:
                        return parsed
                except Exception:
                    continue

        # Fallback: generic dateparser on first 5000 chars
        parsed = dateparser.parse(
            text[:5000],
            settings=self._patterns.get("dateparser_settings", {"DEFAULT_LANGUAGES": ["en"]}),
        )
        return parsed

    def _extract_reference(self, text: str, url: str) -> str | None:
        """Extract jurisdiction-specific reference number."""
        ref_patterns = self._patterns.get("reference_patterns", [])

        for pattern_info in ref_patterns:
            pattern = pattern_info.get("pattern")
            flags = pattern_info.get("flags", 0)
            if not pattern:
                continue

            match = re.search(pattern, text, flags)
            if match:
                # Return first capturing group if present, else full match
                return match.group(1) if match.groups() else match.group(0)

        # Fallback: extract from URL
        return self._extract_reference_from_url(url)

    def _extract_reference_from_url(self, url: str) -> str | None:
        """Attempt to extract reference from URL path."""
        # Common patterns in regulatory URLs
        patterns = [
            r"(RBI/\d{4}-\d{2}/[A-Z]+/\d+)",
            r"(SEBI/HO/\w+/\d+/CIR/\d{4}/\d+)",
            r"(Article\s+\d+[A-Z]?)",
            r"(Annex\s+[IVXLC]+)",
            r"(Recital\s+\d+)",
            r"(\d+\s+FR\s+\d+)",
            r"(FR\s+Doc\.\s+\d{4}-\d{5})",
            r"(RIN\s+\d{4}-\w{2,4})",
        ]

        for pattern in patterns:
            match = re.search(pattern, url, re.IGNORECASE)
            if match:
                return match.group(1) if match.groups() else match.group(0)

        return None

    def _extract_document_type(self, text: str, url: str) -> DocumentType | None:
        """Determine document type from text and URL."""
        doc_type_patterns = self._patterns.get("document_type_patterns", {})
        combined = f"{text} {url}".lower()

        for doc_type_str, patterns in doc_type_patterns.items():
            for pattern in patterns:
                if re.search(pattern, combined, re.IGNORECASE):
                    try:
                        return DocumentType(doc_type_str)
                    except ValueError:
                        logger.debug("Unknown document type in config: %s", doc_type_str)
                        continue

        # Jurisdiction-specific fallbacks
        if self.jurisdiction == Jurisdiction.RBI:
            rbi_keywords = ["notification", "circular", "direction", "master direction"]
            if any(kw in combined for kw in rbi_keywords):
                return DocumentType.NOTIFICATION
            if "press release" in combined or "pressrelease" in combined:
                return DocumentType.PRESS_RELEASE

        elif self.jurisdiction == Jurisdiction.SEBI:
            return DocumentType.CIRCULAR

        elif self.jurisdiction == Jurisdiction.FDA:
            fda_reg_keywords = ["federal register", "fr doc", "final rule", "proposed rule"]
            if any(kw in combined for kw in fda_reg_keywords):
                return DocumentType.REGULATION
            return DocumentType.RSS_ITEM

        elif self.jurisdiction == Jurisdiction.EU_AI_ACT:
            eu_reg_keywords = ["article", "annex", "recital", "chapter", "regulation"]
            if any(kw in combined for kw in eu_reg_keywords):
                return DocumentType.REGULATION
            return DocumentType.NEWS

        return None

    def _detect_language(self, text: str) -> str | None:
        """Basic language detection (can be improved in normalize phase)."""
        sample = text[:2000].lower()

        # English indicators (very common words)
        english_words = [
            "the",
            "and",
            "of",
            "to",
            "in",
            "a",
            "is",
            "for",
            "on",
            "with",
            "as",
            "by",
            "that",
            "be",
        ]
        english_count = sum(1 for w in english_words if f" {w} " in f" {sample} ")

        if english_count >= 4:
            return "en"

        # Could add more languages here
        return "en"  # Default for regulatory docs


def extract_metadata(
    text: str, url: str, jurisdiction: Jurisdiction, patterns_path: Path | None = None
) -> dict[str, Any]:
    """
    Convenience function for one-off metadata extraction.

    Args:
        text: Document text.
        url: Source URL.
        jurisdiction: Jurisdiction enum.
        patterns_path: Optional custom patterns path.

    Returns:
        Metadata dict.
    """
    extractor = MetadataExtractor(jurisdiction, patterns_path)
    return extractor.extract(text, url)
