"""Tests for LanguageDetector (Phase 2b)."""

from __future__ import annotations

from regmon.normalize.language import LanguageDetector, detect_language


class TestLanguageDetector:
    """Tests for LanguageDetector class."""

    def test_english_text(self):
        """English text should be detected with high confidence."""
        text = (
            "The Reserve Bank of India has issued a notification regarding "
            "updated KYC norms for all scheduled commercial banks."
        )
        detector = LanguageDetector(confidence_threshold=0.5)
        lang, confidence = detector.detect(text)

        assert lang == "en"
        assert confidence > 0.5

    def test_hindi_text(self):
        """Hindi (Devanagari) text should be detected."""
        text = "भारतीय रिज़र्व बैंक ने बैंकों के लिए अद्यतन KYC मानदंडों के संबंध में एक अधिसूचना जारी की है।"
        detector = LanguageDetector(confidence_threshold=0.1)
        lang, confidence = detector.detect(text)

        assert lang == "hi"
        assert confidence > 0.1

    def test_short_text_fallback(self):
        """Short text (< 20 chars) should use fallback."""
        text = "Short text."
        detector = LanguageDetector(fallback_lang="en")
        lang, confidence = detector.detect(text)

        assert lang == "en"
        assert confidence == 0.1

    def test_empty_text(self):
        """Empty text should return fallback."""
        detector = LanguageDetector(fallback_lang="en")
        lang, confidence = detector.detect("")
        assert lang == "en"
        assert confidence == 0.1

    def test_whitespace_only(self):
        """Whitespace-only text should return fallback."""
        detector = LanguageDetector(fallback_lang="en")
        lang, confidence = detector.detect("   \n\t  ")
        assert lang == "en"
        assert confidence == 0.1

    def test_mixed_lang_english_dominant(self):
        """Mixed English/Hindi should detect dominant language."""
        text = "The Reserve Bank of India issued notification. भारतीय रिज़र्व बैंक ने अधिसूचना जारी की।"
        detector = LanguageDetector(confidence_threshold=0.1)
        lang, confidence = detector.detect(text)

        # Should detect one of the two, English likely dominant due to more words
        assert lang in ("en", "hi")
        assert confidence > 0.1

    def test_convenience_function(self):
        """Test detect_language convenience function."""
        text = "This is English text."
        lang, confidence = detect_language(text)
        assert lang == "en"
        assert confidence > 0.5


class TestLanguageDetectorFallback:
    """Tests specifically for fallback behavior when langdetect unavailable or fails."""

    def test_heuristic_detection_english(self):
        """Test heuristic detection for English without langdetect."""
        detector = LanguageDetector(confidence_threshold=0.5)
        # Directly test heuristic by calling internal method
        text = "The Reserve Bank of India has issued a notification regarding KYC norms."
        lang, confidence = detector._heuristic_detect(text)

        assert lang == "en"
        assert confidence > 0.1

    def test_heuristic_detection_hindi(self):
        """Test heuristic detection for Hindi (Devanagari script)."""
        detector = LanguageDetector(confidence_threshold=0.5)
        text = "भारतीय रिज़र्व बैंक ने बैंकों के लिए अद्यतन मानदंड जारी किए हैं।"
        lang, confidence = detector._heuristic_detect(text)

        assert lang == "hi"
        assert confidence > 0.1

    def test_heuristic_unknown_script_fallback(self):
        """Unknown script should fall back to default."""
        detector = LanguageDetector(fallback_lang="en")
        text = "🎉🎊🎈"  # Emojis only - no recognizable script
        _lang, confidence = detector._heuristic_detect(text)

        # Should fall back to default or return low confidence
        assert confidence <= 0.5
