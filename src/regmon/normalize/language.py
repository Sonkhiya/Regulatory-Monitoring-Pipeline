"""Language detection using lingua-py (Phase 2b)."""

from __future__ import annotations

import logging
from typing import Any

logger = logging.getLogger(__name__)

# Try to import lingua
try:
    from lingua import LanguageDetectorBuilder

    LINGUA_AVAILABLE = True
except ImportError:
    LINGUA_AVAILABLE = False
    logger.debug("lingua not available, using heuristic fallback")


# Heuristic patterns for fallback (when lingua unavailable)
# Maps ISO 639-1 code -> patterns and script info
LANGUAGE_PATTERNS: dict[str, dict[str, Any]] = {
    "en": {
        "patterns": [
            r"\b(the|and|or|of|to|a|in|is|that|for|on|with|as|by|at|from)\b",
            r"\b(this|that|have|has|had|will|would|could|should|may|might|must)\b",
        ],
        "scripts": ["Latn"],
        "name": "English",
    },
    "hi": {
        "patterns": [r"[ऀ-ॿ]", r"[।॥]"],
        "scripts": ["Deva"],
        "name": "Hindi",
    },
    "bn": {
        "patterns": [r"[ঀ-৿]", r"[।॥]"],
        "scripts": ["Beng"],
        "name": "Bengali",
    },
    "ta": {
        "patterns": [r"[஀-௿]", r"[「『]"],
        "scripts": ["Taml"],
        "name": "Tamil",
    },
    "te": {
        "patterns": [r"[ఀ-౿]", r"[『']"],
        "scripts": ["Telu"],
        "name": "Telugu",
    },
    "mr": {
        "patterns": [r"[ऀ-ॿ]", r"[。॥]"],
        "scripts": ["Deva"],
        "name": "Marathi",
    },
    "gu": {
        "patterns": [r"[઀-૿]", r"['　-〿]"],
        "scripts": ["Gujr"],
        "name": "Gujarati",
    },
    "kn": {
        "patterns": [r"[ಀ-೿]", r"['　-〿]"],
        "scripts": ["Knda"],
        "name": "Kannada",
    },
    "ml": {
        "patterns": [r"[ഀ-ൿ]", r"[『』]"],
        "scripts": ["Mlym"],
        "name": "Malayalam",
    },
    "pa": {
        "patterns": [r"[਀-੿]", r"['　-〿]"],
        "scripts": ["Guru"],
        "name": "Punjabi",
    },
    "ur": {
        "patterns": [r"[؀-ۿ]", r"[.!?]"],
        "scripts": ["Arab"],
        "name": "Urdu",
    },
    "zh": {
        "patterns": [r"[一-鿿]", r"[.!?,、。]"],
        "scripts": ["Hani"],
        "name": "Chinese",
    },
    "ja": {
        "patterns": [r"[぀-ヿ]", r"[.!?、。]"],
        "scripts": ["Hira", "Kana"],
        "name": "Japanese",
    },
    "ko": {
        "patterns": [r"[가-힣]", r"[.!?,]"],
        "scripts": ["Hang"],
        "name": "Korean",
    },
    "ar": {
        "patterns": [r"[؀-ۿ]", r"[.!?]"],
        "scripts": ["Arab"],
        "name": "Arabic",
    },
    "fa": {
        "patterns": [r"[؀-ۿ]", r"[.!?]"],
        "scripts": ["Arab"],
        "name": "Persian",
    },
    "ru": {
        "patterns": [r"[Ѐ-ӿ]", r"[.!?]"],
        "scripts": ["Cyrl"],
        "name": "Russian",
    },
    "de": {
        "patterns": [
            r"\b(der|die|das|und|oder|in|den|von|zu|mit|sich|des|auf|für|ist|im|dem|nicht|ein|eine|als|so|mehr)\b"
        ],
        "scripts": ["Latn"],
        "name": "German",
    },
    "fr": {
        "patterns": [
            r"\b(le|la|les|un|une|des|et|ou|de|à|en|du|au|aux|est|pour|sur|avec|dans|par|son|sa|ses|ce|cet|cette|ces|qui|que|dont|où|si|mais|donc|car|ni|or)\b"
        ],
        "scripts": ["Latn"],
        "name": "French",
    },
    "es": {
        "patterns": [
            r"\b(el|la|los|las|un|una|unos|unas|y|o|de|a|en|del|al|es|por|para|con|sin|sobre|entre|desde|hasta|durante|mediante|según|contra|tras|bajo|ante|cabe)\b"
        ],
        "scripts": ["Latn"],
        "name": "Spanish",
    },
    "it": {
        "patterns": [
            r"\b(il|lo|la|gli|le|un|uno|una|e|o|di|a|da|in|con|su|per|tra|fra|che|chi|il|la|lo|gli|le|un|uno|una|e|o|ma|perché|quando|come|dove|chi|che|cosa|quale|quanto|quanti|quante)\b"
        ],
        "scripts": ["Latn"],
        "name": "Italian",
    },
    "pt": {
        "patterns": [
            r"\b(o|a|os|as|um|uma|uns|umas|e|ou|de|a|em|do|da|dos|das|no|na|nos|nas|por|para|com|sem|sobre|entre|desde|até|durante|mediante|segundo|conforme|contra|trás|abaixo|acima|ante|após|através|bem|como|contra|conforme)\b"
        ],
        "scripts": ["Latn"],
        "name": "Portuguese",
    },
}


# Build lingua detector lazily (only once)
_lingua_detector = None


def _get_lingua_detector():
    """Get or create the lingua language detector."""
    global _lingua_detector
    if _lingua_detector is None and LINGUA_AVAILABLE:
        # Build detector for all ISO 639-1 languages supported by lingua
        _lingua_detector = LanguageDetectorBuilder.from_all_languages().build()
    return _lingua_detector


def _lingua_to_iso639_1(lingua_code) -> str:
    """Convert a lingua Language enum value to a lowercase ISO 639-1 code."""
    # lingua's Language enum members expose iso_code_639_1 (IsoCode639_1 enum
    # whose member names ARE the alpha-2 codes, e.g. IsoCode639_1.EN -> "en").
    iso = getattr(lingua_code, "iso_code_639_1", None)
    if iso is not None and hasattr(iso, "name"):
        return iso.name.lower()
    # Fall back to the Language enum member name lowercased.
    return lingua_code.name.lower()


def _heuristic_detect(text: str, fallback_lang: str) -> tuple[str, float]:
    """
    Heuristic language detection based on script and common word patterns.

    Used as fallback when lingua is unavailable or low-confidence.

    Args:
        text: Input text.
        fallback_lang: Fallback language code.

    Returns:
        Tuple of (language_code, confidence).
    """
    import re

    if not text or len(text.strip()) < 10:
        return fallback_lang, 0.1

    scores: dict[str, int] = {}

    for lang_code, lang_info in LANGUAGE_PATTERNS.items():
        score = 0
        for pattern in lang_info["patterns"]:
            matches = len(re.findall(pattern, text, re.IGNORECASE))
            score += matches
        if score > 0:
            scores[lang_code] = score

    if not scores:
        return fallback_lang, 0.1

    best_lang = max(scores.keys(), key=lambda k: scores[k])
    max_score = scores[best_lang]

    total_chars = max(len(text), 1)
    confidence = min(max_score / (total_chars / 100), 1.0)

    logger.debug(
        "Heuristic detection: lang=%s, score=%d, confidence=%.2f",
        best_lang,
        max_score,
        confidence,
    )

    return best_lang, confidence


class LanguageDetector:
    """Detects language of text using lingua-py with heuristic fallback."""

    def __init__(
        self,
        confidence_threshold: float = 0.5,
        fallback_lang: str = "en",
    ) -> None:
        """
        Initialize language detector.

        Args:
            confidence_threshold: Minimum confidence for lingua result (default: 0.5).
            fallback_lang: ISO 639-1 code for fallback (default: "en").
        """
        self.confidence_threshold = confidence_threshold
        self.fallback_lang = fallback_lang
        self._detector = _get_lingua_detector()

    def _heuristic_detect(self, text: str) -> tuple[str, float]:
        """Bound heuristic fallback using this detector's fallback_lang."""
        return _heuristic_detect(text, self.fallback_lang)

    def detect(self, text: str) -> tuple[str, float]:
        """
        Detect language of text.

        Args:
            text: Input text to analyze.

        Returns:
            Tuple of (ISO 639-1 language code, confidence score 0-1).
        """
        if not text or not text.strip():
            logger.debug("Empty text, returning fallback language")
            return self.fallback_lang, 0.1

        # Short text gets lower confidence handling via lingua
        if len(text.strip()) < 20:
            logger.debug("Text too short (%d chars), using fallback", len(text.strip()))
            return self.fallback_lang, 0.1

        # Try lingua first
        if self._detector is not None:
            try:
                # lingua returns None for unknown/unreliable detection
                lingua_lang = self._detector.detect_language_of(text)
                if lingua_lang is not None:
                    lang_code = _lingua_to_iso639_1(lingua_lang)

                    # Get confidence value
                    confidences = self._detector.compute_language_confidence_values(text)
                    if confidences:
                        best_conf = confidences[0]
                        confidence = best_conf.value
                        logger.debug("lingua: lang=%s, confidence=%.4f", lang_code, confidence)
                        if confidence >= self.confidence_threshold:
                            return lang_code, confidence
                        else:
                            logger.debug(
                                "lingua confidence %.4f below threshold %.2f, using fallback",
                                confidence,
                                self.confidence_threshold,
                            )
                    else:
                        logger.debug("lingua returned no confidence values")
                else:
                    logger.debug("lingua returned no language for text")
            except Exception as e:
                logger.debug("lingua detection error: %s, using fallback", e)
        else:
            logger.debug("lingua not available, using heuristic")

        # Fallback to heuristic
        return _heuristic_detect(text, self.fallback_lang)


def detect_language(text: str, confidence_threshold: float = 0.5) -> tuple[str, float]:
    """Convenience function for one-off language detection."""
    detector = LanguageDetector(confidence_threshold=confidence_threshold)
    return detector.detect(text)


__all__ = ["LanguageDetector", "detect_language"]
