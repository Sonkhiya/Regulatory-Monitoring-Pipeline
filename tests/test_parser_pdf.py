"""Tests for PDF parser."""

from __future__ import annotations

from regmon.parser.pdf_parser import PDFParser, parse_pdf

FIXTURES_DIR = __file__.rsplit("/", 1)[0] + "/fixtures/parser"


class TestPDFParser:
    """Tests for PDFParser class."""

    def test_parse_empty_bytes(self) -> None:
        """Test parsing empty PDF bytes."""
        parser = PDFParser()
        text, metadata = parser.parse(b"")
        assert text == ""
        assert metadata["page_count"] == 0
        assert metadata["is_scanned"] is True

    def test_parse_invalid_pdf(self) -> None:
        """Test parsing invalid PDF bytes."""
        parser = PDFParser()
        text, metadata = parser.parse(b"not a pdf")
        assert text == ""
        assert metadata["page_count"] == 0
        assert metadata["is_scanned"] is True
        assert "error" in metadata

    def test_parse_sample_pdf(self) -> None:
        """Test parsing sample PDF fixture."""
        parser = PDFParser()
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parser.parse(content)

        # Should handle the minimal PDF
        assert metadata["page_count"] >= 1
        # Text may be empty due to minimal PDF structure
        assert "is_scanned" in metadata

    def test_extract_first_page_text(self) -> None:
        """Test extracting first page text."""
        parser = PDFParser()
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        text = parser.extract_first_page_text(content, max_chars=100)
        # Should return a string (may be empty for minimal PDF)
        assert isinstance(text, str)

    def test_extract_first_page_text_empty(self) -> None:
        """Test extracting first page from empty PDF."""
        parser = PDFParser()
        text = parser.extract_first_page_text(b"", max_chars=100)
        assert text == ""

    def test_scanned_pdf_detection(self) -> None:
        """Test detection of scanned/image-only PDF."""
        parser = PDFParser()
        fixture_path = FIXTURES_DIR + "/scanned.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        text, metadata = parser.parse(content)

        # This PDF has no extractable text
        assert text == ""
        assert metadata["is_scanned"] is True

    def test_pdf_metadata_extraction(self) -> None:
        """Test PDF metadata extraction (title, author, etc.)."""
        # Our minimal PDF doesn't have metadata, just check structure
        parser = PDFParser()
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parser.parse(content)

        # Check expected metadata keys exist
        expected_keys = [
            "page_count",
            "is_scanned",
            "toc_entries",
            "title",
            "author",
            "subject",
            "creator",
            "producer",
            "creation_date",
            "modification_date",
        ]
        for key in expected_keys:
            assert key in metadata

    def test_toc_extraction_disabled(self) -> None:
        """Test TOC extraction when disabled."""
        parser = PDFParser(extract_toc=False)
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parser.parse(content)
        assert metadata["toc_entries"] == []

    def test_toc_extraction_enabled(self) -> None:
        """Test TOC extraction when enabled (no TOC in sample)."""
        parser = PDFParser(extract_toc=True)
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parser.parse(content)
        # Empty list is fine for PDFs without outline
        assert isinstance(metadata["toc_entries"], list)


class TestParsePdfConvenience:
    """Tests for parse_pdf convenience function."""

    def test_parse_pdf_function(self) -> None:
        """Test parse_pdf convenience function."""
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parse_pdf(content)
        assert isinstance(metadata, dict)
        assert "page_count" in metadata

    def test_parse_pdf_with_toc_disabled(self) -> None:
        """Test parse_pdf with toc disabled."""
        fixture_path = FIXTURES_DIR + "/sample.pdf"
        with open(fixture_path, "rb") as f:
            content = f.read()
        _text, metadata = parse_pdf(content, extract_toc=False)
        assert metadata["toc_entries"] == []
