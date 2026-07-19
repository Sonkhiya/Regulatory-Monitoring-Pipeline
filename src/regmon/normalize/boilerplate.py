"""Boilerplate stripping using n-gram frequency analysis (Phase 2b)."""

from __future__ import annotations

import logging
import re
from collections import Counter
from typing import Any

logger = logging.getLogger(__name__)


def _get_ngrams(text: str, n: int) -> list[str]:
    """Extract character n-grams from text."""
    if len(text) < n:
        return []
    return [text[i : i + n] for i in range(len(text) - n + 1)]


class BoilerplateStripper:
    """Strips boilerplate by learning persistent n-grams across documents per site."""

    def __init__(
        self,
        n_gram_size: int = 4,
        min_frequency: int = 3,
        min_length: int = 50,
    ) -> None:
        """
        Initialize boilerplate stripper.

        Args:
            n_gram_size: Size of character n-grams to track (default: 4).
            min_frequency: Minimum occurrences before n-gram is considered boilerplate (default: 3).
            min_length: Minimum text length to attempt stripping (default: 50).
        """
        self.n_gram_size = n_gram_size
        self.min_frequency = min_frequency
        self.min_length = min_length

        # Per-site n-gram frequency tables
        self._ngram_counts: dict[str, Counter[str]] = {}
        # Per-site identified boilerplate n-grams
        self._boilerplate_ngrams: dict[str, set[str]] = {}

    def _get_site_counts(self, site_key: str) -> Counter[str]:
        """Get or create n-gram counter for site."""
        if site_key not in self._ngram_counts:
            self._ngram_counts[site_key] = Counter()
        return self._ngram_counts[site_key]

    def _get_site_boilerplate(self, site_key: str) -> set[str]:
        """Get or create boilerplate n-gram set for site."""
        if site_key not in self._boilerplate_ngrams:
            self._boilerplate_ngrams[site_key] = set()
        return self._boilerplate_ngrams[site_key]

    def strip(self, text: str, site_key: str = "default") -> tuple[str, dict[str, Any]]:
        """
        Strip boilerplate from text.

        First call learns n-grams; subsequent calls strip n-grams seen
        at least min_frequency times for the same site_key.

        Args:
            text: Input text to clean.
            site_key: Site identifier for tracking boilerplate (default: "default").

        Returns:
            Tuple of (clean_text, strip_info) where strip_info contains:
            - boilerplate_removed: bool
            - ngrams_stripped: list[str]
            - chars_removed: int
        """
        strip_info = {
            "boilerplate_removed": False,
            "ngrams_stripped": [],
            "chars_removed": 0,
        }

        if not text or not text.strip():
            return text, strip_info

        if len(text) < self.min_length:
            logger.debug(
                "Text shorter than min_length (%d), skipping boilerplate strip",
                self.min_length,
            )
            return text, strip_info

        site_counts = self._get_site_counts(site_key)
        site_boilerplate = self._get_site_boilerplate(site_key)

        # Step 1: Strip using already confirmed boilerplate n-grams (from PREVIOUS documents)
        clean_text = text
        if site_boilerplate:
            original_len = len(clean_text)
            stripped_ngrams = []

            for ngram in sorted(site_boilerplate, key=len, reverse=True):
                if ngram in clean_text:
                    clean_text = clean_text.replace(ngram, " ")
                    stripped_ngrams.append(ngram)

            clean_text = re.sub(r"\s+", " ", clean_text).strip()
            chars_removed = original_len - len(clean_text)

            if chars_removed > 0:
                strip_info["boilerplate_removed"] = True
                strip_info["ngrams_stripped"] = stripped_ngrams
                strip_info["chars_removed"] = chars_removed
                logger.debug(
                    "Stripped %d boilerplate n-grams from %s, removed %d chars",
                    len(stripped_ngrams),
                    site_key,
                    chars_removed,
                )

        # Step 2: Extract n-grams from clean text (or original if nothing stripped)
        # and update counts for FUTURE stripping
        text_ngrams = _get_ngrams(clean_text, self.n_gram_size)
        text_ngram_counts = Counter(text_ngrams)
        site_counts.update(text_ngram_counts)

        # Step 3: Identify newly confirmed boilerplate n-grams for future stripping
        for ngram, count in site_counts.items():
            if count >= self.min_frequency and ngram not in site_boilerplate:
                site_boilerplate.add(ngram)

        return clean_text, strip_info

    def reset(self, site_key: str | None = None) -> None:
        """
        Clear learned n-gram frequencies.

        Args:
            site_key: Specific site to reset, or None to reset all.
        """
        if site_key:
            self._ngram_counts.pop(site_key, None)
            self._boilerplate_ngrams.pop(site_key, None)
        else:
            self._ngram_counts.clear()
            self._boilerplate_ngrams.clear()

    def get_stats(self, site_key: str | None = None) -> dict[str, Any]:
        """Get statistics about learned boilerplate."""
        if site_key:
            counts = self._ngram_counts.get(site_key, Counter())
            boilerplate = self._boilerplate_ngrams.get(site_key, set())
            return {
                "site_key": site_key,
                "total_ngrams": len(counts),
                "boilerplate_ngrams": len(boilerplate),
                "top_ngrams": counts.most_common(10),
            }
        return {
            "sites": list(self._ngram_counts.keys()),
            "total_sites": len(self._ngram_counts),
            "total_boilerplate_ngrams": sum(len(v) for v in self._boilerplate_ngrams.values()),
        }


def strip_boilerplate(text: str, site_key: str = "default") -> tuple[str, dict[str, Any]]:
    """Convenience function using default BoilerplateStripper instance."""
    stripper = BoilerplateStripper()
    return stripper.strip(text, site_key)


__all__ = ["BoilerplateStripper", "strip_boilerplate"]
