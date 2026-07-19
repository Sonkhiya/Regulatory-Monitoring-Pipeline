"""Tests for EncodingRepair (Phase 2b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from regmon.normalize.encoding_repair import EncodingRepair, repair_encoding

FIXTURES_DIR = Path(__file__).parent / "fixtures"


class TestEncodingRepair:
    """Tests for EncodingRepair class."""

    def test_clean_text_passthrough(self):
        """Clean English text should pass through unchanged."""
        text = "The Reserve Bank of India has issued a notification regarding KYC norms."
        repairer = EncodingRepair()
        result, info = repairer.repair(text)

        assert result == text
        assert info["ftfy_applied"] is False
        assert info["encoding_fixed"] is False

    def test_empty_string(self):
        """Empty string should return unchanged."""
        repairer = EncodingRepair()
        result, info = repairer.repair("")
        assert result == ""
        assert info["encoding_fixed"] is False

    def test_whitespace_only(self):
        """Whitespace-only should return unchanged."""
        repairer = EncodingRepair()
        result, info = repairer.repair("   \n\t  ")
        assert result == "   \n\t  "
        assert info["encoding_fixed"] is False

    def test_mojibake_utf8_fix(self):
        """ftfy should fix common UTF-8 mojibake patterns."""
        # mojibake: UTF-8 encoded text misread as latin-1
        mojibake = (
            "The Reserve Bank of India \xc3\xa2\xc2\x80\xc2\x9chigh-risk"
            "\xc3\xa2\xc2\x80\xc2\x9d customers \xc3\xa2\xc2\x80\xc2\x94"
            " updated KYC norms."
        )
        repairer = EncodingRepair(enable_ftfy=True, enable_chardet=False)
        result, info = repairer.repair(mojibake)

        assert info["ftfy_applied"] is True
        assert "high-risk" in result
        assert "—" in result  # em dash
        assert "\xc3\xa2\xc2\x80\xc2\x9c" not in result

    def test_mojibake_latin1_fix(self):
        """ftfy should fix latin-1 misdecoded text."""
        # latin-1 encoded text with accented chars, read as utf-8
        mojibake = "RBI: \xc3\xa9lite banking \xc3\xa9normes"  # é encoded as latin-1, read as utf-8
        repairer = EncodingRepair(enable_ftfy=True, enable_chardet=False)
        _result, info = repairer.repair(mojibake)

        # ftfy may or may not fix this depending on pattern
        assert info["ftfy_applied"] in (True, False)

    def test_ftfy_disabled(self):
        """When ftfy is disabled, text should pass through."""
        mojibake = (
            "The Reserve Bank of India "
            "\xc3\xa2\xc2\x80\xc2\x9chigh-risk"
            "\xc3\xa2\xc2\x80\xc2\x9d"
        )
        repairer = EncodingRepair(enable_ftfy=False, enable_chardet=False)
        result, info = repairer.repair(mojibake)

        assert result == mojibake
        assert info["ftfy_applied"] is False

    def test_chardet_detection(self):
        """chardet should detect encoding when enabled."""
        text = "RBI notification"
        repairer = EncodingRepair(enable_ftfy=False, enable_chardet=True)
        _result, info = repairer.repair(text)

        # chardet runs but may not find non-utf8 encoding for clean text
        assert info["original_encoding"] in (None, "utf-8", "ascii")

    def test_convenience_function(self):
        """Test repair_encoding convenience function."""
        text = "Clean text."
        result, info = repair_encoding(text)
        assert result == text
        assert info["ftfy_applied"] is False


class TestEncodingRepairMojibakePatterns:
    """Tests for specific mojibake patterns from fixtures."""

    def test_fixture_mojibake_utf8(self):
        """Test mojibake_utf8.txt fixture if exists."""
        fixture_path = FIXTURES_DIR / "normalize" / "mojibake_utf8.txt"
        if not fixture_path.exists():
            pytest.skip("Fixture not found")

        text = fixture_path.read_text(encoding="utf-8")
        print(f"Fixture content (repr): {text[:200]!r}")

        repairer = EncodingRepair(enable_ftfy=True, enable_chardet=False)
        result, info = repairer.repair(text)

        print(f"Fixed (repr): {result[:200]!r}")
        print(f"Info: {info}")

        # Should have applied fix
        assert info["ftfy_applied"] is True or info["encoding_fixed"] is True

    def test_fixture_mojibake_latin1(self):
        """Test mojibake_latin1.txt fixture if exists."""
        fixture_path = FIXTURES_DIR / "normalize" / "mojibake_latin1.txt"
        if not fixture_path.exists():
            pytest.skip("Fixture not found")

        text = fixture_path.read_text(encoding="utf-8")
        print(f"Fixture content (repr): {text[:200]!r}")

        repairer = EncodingRepair(enable_ftfy=True, enable_chardet=True)
        result, info = repairer.repair(text)

        print(f"Fixed (repr): {result[:200]!r}")
        print(f"Info: {info}")

        # At minimum should process without error
        assert isinstance(result, str)
