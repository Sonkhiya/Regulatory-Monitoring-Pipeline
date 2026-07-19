"""Tests for BoilerplateStripper (Phase 2b)."""

from __future__ import annotations

from pathlib import Path

import pytest

from regmon.normalize.boilerplate import BoilerplateStripper

FIXTURES_DIR = Path(__file__).parent / "fixtures" / "normalize"


class TestBoilerplateStripper:
    """Tests for BoilerplateStripper class."""

    def test_first_call_learns_only(self):
        """First call with text should learn n-grams but not strip."""
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)
        text = (
            "Home | About Us | Press Releases | Contact Us\n"
            "Main content here.\n"
            "Footer | Privacy | Terms"
        )
        result, info = stripper.strip(text, "test_site")

        # First call - no stripping yet (learning phase)
        assert info["boilerplate_removed"] is False
        assert result == text

    def test_second_call_strips_boilerplate(self):
        """Second call with same boilerplate should strip it."""
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        # First document - learning
        text1 = (
            "Home | About Us | Press Releases | Contact Us\n"
            "RBI notification content here.\n"
            "Footer | Privacy | Terms"
        )
        stripper.strip(text1, "test_site")

        # Second document with same boilerplate - should strip
        text2 = (
            "Home | About Us | Press Releases | Contact Us\n"
            "SEBI circular content here.\n"
            "Footer | Privacy | Terms"
        )
        result, info = stripper.strip(text2, "test_site")

        assert info["boilerplate_removed"] is True
        assert "Home | About Us | Press Releases | Contact Us" not in result
        assert "Footer | Privacy | Terms" not in result
        assert "SEBI circular content here" in result

    def test_min_length_threshold(self):
        """Text shorter than min_length should not be processed."""
        stripper = BoilerplateStripper(min_length=50)
        short_text = "Short text"
        result, info = stripper.strip(short_text, "test_site")

        assert info["boilerplate_removed"] is False
        assert result == short_text

    def test_reset_clears_learned_ngrams(self):
        """reset() should clear learned n-grams for a site."""
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        text1 = "Home | About Us | Press Releases | Contact Us\nContent 1\nFooter"
        stripper.strip(text1, "test_site")
        stripper.strip(text1, "test_site")  # Now boilerplate learned

        # Reset this site
        stripper.reset("test_site")

        # Should be back to learning phase
        text2 = "Home | About Us | Press Releases | Contact Us\nContent 2\nFooter"
        _result, info = stripper.strip(text2, "test_site")
        assert info["boilerplate_removed"] is False

    def test_different_site_keys_independent(self):
        """Different site_keys should track boilerplate independently."""
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        text = "Home | About Us | Press Releases | Contact Us\nContent\nFooter"
        stripper.strip(text, "site_a")
        stripper.strip(text, "site_a")  # Learn for site_a

        # site_b hasn't learned yet
        _result, info = stripper.strip(text, "site_b")
        assert info["boilerplate_removed"] is False

        # site_a has learned
        _result, info = stripper.strip(text, "site_a")
        assert info["boilerplate_removed"] is True

    def test_empty_text(self):
        """Empty text should return early."""
        stripper = BoilerplateStripper()
        result, info = stripper.strip("", "test_site")
        assert result == ""
        assert info["boilerplate_removed"] is False

    def test_get_stats(self):
        """get_stats should return tracking info."""
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        text = "Home | About Us | Press Releases | Contact Us\nContent\nFooter"
        stripper.strip(text, "site_a")
        stripper.strip(text, "site_a")

        stats = stripper.get_stats("site_a")
        assert stats["site_key"] == "site_a"
        assert stats["total_ngrams"] > 0
        assert "boilerplate_ngrams" in stats

        all_stats = stripper.get_stats()
        assert "sites" in all_stats
        assert "site_a" in all_stats["sites"]


class TestBoilerplateStripperFixtures:
    """Tests using fixture files."""

    def test_rbi_boilerplate_fixture(self):
        """Test stripping RBI fixture has repeated navigation/footer."""
        fixture_path = FIXTURES_DIR / "boilerplate_rbi.txt"
        if not fixture_path.exists():
            pytest.skip("RBI fixture not found")

        text = fixture_path.read_text(encoding="utf-8")
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        # First pass - learn
        _result1, info1 = stripper.strip(text, "rbi.org.in")
        assert info1["boilerplate_removed"] is False

        # Second pass - should strip
        result2, info2 = stripper.strip(text, "rbi.org.in")
        assert info2["boilerplate_removed"] is True
        assert "MAIN CONTENT" in result2  # Content preserved
        assert "NAVIGATION" not in result2 or "NAVIGATION" not in result2.lower()

    def test_sebi_boilerplate_fixture(self):
        """SEBI fixture has repeated navigation/footer."""
        fixture_path = FIXTURES_DIR / "boilerplate_sebi.txt"
        if not fixture_path.exists():
            pytest.skip("SEBI fixture not found")

        text = fixture_path.read_text(encoding="utf-8")
        stripper = BoilerplateStripper(n_gram_size=4, min_frequency=2)

        # First pass - learn
        _result1, info1 = stripper.strip(text, "sebi.gov.in")
        assert info1["boilerplate_removed"] is False

        # Second pass - should strip
        result2, info2 = stripper.strip(text, "sebi.gov.in")
        assert info2["boilerplate_removed"] is True
        assert "MAIN CONTENT" in result2
