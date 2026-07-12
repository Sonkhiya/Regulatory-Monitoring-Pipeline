"""Tests for ParserAgent orchestrator."""

from __future__ import annotations

import asyncio
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

import pytest

from regmon.models import Jurisdiction, RawDocument
from regmon.models.documents import ParsedDocument
from regmon.parser import ParserAgent, detect_content_type

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures" / "parser"


class TestDetectContentType:
    """Tests for detect_content_type function."""

    def test_detect_pdf_from_header(self) -> None:
        """Test PDF detection from Content-Type header."""
        headers = {"Content-Type": "application/pdf"}
        assert detect_content_type(b"%PDF-1.4", headers) == "pdf"

    def test_detect_html_from_header(self) -> None:
        """Test HTML detection from Content-Type header."""
        headers = {"Content-Type": "text/html; charset=utf-8"}
        assert detect_content_type(b"<html>", headers) == "html"

    def test_detect_xml_from_header(self) -> None:
        """Test XML detection from Content-Type header."""
        headers = {"Content-Type": "application/xml"}
        assert detect_content_type(b"<?xml?>", headers) == "html"  # XML treated as HTML

    def test_detect_rss_from_header(self) -> None:
        """Test RSS detection from Content-Type header."""
        headers = {"Content-Type": "application/rss+xml"}
        assert detect_content_type(b"<rss>", headers) == "html"  # RSS treated as HTML

    def test_detect_pdf_from_magic_bytes(self) -> None:
        """Test PDF detection from magic bytes."""
        assert detect_content_type(b"%PDF-1.4 content", {}) == "pdf"

    def test_detect_html_from_doctype(self) -> None:
        """Test HTML detection from DOCTYPE."""
        assert detect_content_type(b"<!DOCTYPE html><html>", {}) == "html"

    def test_detect_html_from_html_tag(self) -> None:
        """Test HTML detection from <html> tag."""
        assert detect_content_type(b"<html><body></body></html>", {}) == "html"

    def test_detect_xml_from_declaration(self) -> None:
        """Test HTML detection from XML declaration."""
        assert detect_content_type(b"<?xml version='1.0'?>", {}) == "html"

    def test_detect_rss_from_tag(self) -> None:
        """Test HTML detection from RSS tag."""
        assert detect_content_type(b"<rss version='2.0'>", {}) == "html"

    def test_detect_atom_from_tag(self) -> None:
        """Test HTML detection from Atom feed tag."""
        assert detect_content_type(b"<feed xmlns='http://www.w3.org/2005/Atom'>", {}) == "html"

    def test_detect_unknown(self) -> None:
        """Test unknown content type."""
        assert detect_content_type(b"random bytes", {}) == "unknown"
        assert detect_content_type(b"", {}) == "unknown"


class TestParserAgent:
    """Tests for ParserAgent class."""

    @pytest.fixture
    def agent(self) -> ParserAgent:
        """Create a ParserAgent instance."""
        return ParserAgent(max_concurrent=2)

    @pytest.fixture
    def sample_rbi_raw_doc(self) -> RawDocument:
        """Create a sample RBI RawDocument."""
        fixture_path = FIXTURES_DIR / "rbi_notification.html"
        if fixture_path.exists():
            content = fixture_path.read_bytes()
        else:
            # Use content that matches the RBI reference patterns
            content = (
                b"<html><head><title>RBI Test</title></head>"
                b"<body>RBI/2024-25/DBR/123 "
                b"DBR.No.123/456.789.123/2024-25 15 Jan 2024</body></html>"
            )

        return RawDocument(
            source_id="rbi_notifications",
            url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
            content_bytes=content,
            headers={"Content-Type": "text/html; charset=utf-8"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            http_status=200,
        )

    @pytest.fixture
    def sample_pdf_raw_doc(self) -> RawDocument:
        """Create a sample PDF RawDocument."""
        pdf_path = FIXTURES_DIR / "sample.pdf"
        if pdf_path.exists():
            content = pdf_path.read_bytes()
        else:
            # Minimal PDF bytes
            content = b"%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF"

        return RawDocument(
            source_id="test_pdf",
            url="https://example.com/document.pdf",
            content_bytes=content,
            headers={"Content-Type": "application/pdf"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            http_status=200,
        )

    async def test_parse_html_document(
        self, agent: ParserAgent, sample_rbi_raw_doc: RawDocument
    ) -> None:
        """Test parsing an HTML document."""
        result = await agent.parse(sample_rbi_raw_doc, Jurisdiction.RBI)
        assert result is not None
        assert isinstance(result, ParsedDocument)
        assert result.url == sample_rbi_raw_doc.url
        assert result.title != "Untitled"
        assert len(result.body_text) > 0
        assert result.doc_id is not None
        assert len(result.doc_id) == 16  # SHA256 truncated

    async def test_parse_pdf_document(
        self, agent: ParserAgent, sample_pdf_raw_doc: RawDocument
    ) -> None:
        """Test parsing a PDF document."""
        result = await agent.parse(sample_pdf_raw_doc, Jurisdiction.RBI)
        assert result is not None
        assert isinstance(result, ParsedDocument)
        assert result.url == sample_pdf_raw_doc.url
        assert result.doc_id is not None

    async def test_parse_sets_metadata(
        self, agent: ParserAgent, sample_rbi_raw_doc: RawDocument
    ) -> None:
        """Test that parsed document has jurisdiction metadata."""
        result = await agent.parse(sample_rbi_raw_doc, Jurisdiction.RBI)
        assert result is not None
        # RBI notification should have these metadata fields
        assert result.document_type is not None
        assert result.reference_number is not None
        # Date may or may not be extracted depending on fixture content

    async def test_parse_empty_content(self, agent: ParserAgent) -> None:
        """Test parsing document with empty content."""
        raw_doc = RawDocument(
            url="https://example.com/empty",
            content_bytes=b"",
            headers={},
            fetched_at=datetime(2024, 1, 15),
            source_id="test",
            http_status=200,
        )
        result = await agent.parse(raw_doc, Jurisdiction.RBI)
        assert result is not None  # Should still return a document
        assert result.body_text == ""

    async def test_parse_unknown_content_type(self, agent: ParserAgent) -> None:
        """Test parsing unknown content type falls back to HTML."""
        raw_doc = RawDocument(
            url="https://example.com/unknown",
            content_bytes=b"<html><body>Plain text content</body></html>",
            headers={"Content-Type": "text/plain"},
            fetched_at=datetime(2024, 1, 15),
            source_id="test",
            http_status=200,
        )
        result = await agent.parse(raw_doc, Jurisdiction.RBI)
        assert result is not None
        assert result.body_text != ""

    async def test_parse_batch(self, agent: ParserAgent, sample_rbi_raw_doc: RawDocument) -> None:
        """Test parsing multiple documents concurrently."""
        raw_docs = [
            sample_rbi_raw_doc,
            RawDocument(
                source_id="rbi_notifications",
                url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12346",
                content_bytes=(
                    b"<html><head><title>RBI Test 2</title></head>"
                    b"<body>RBI content 2 DBR.No.456</body></html>"
                ),
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 16, 12, 0, 0),
                http_status=200,
            ),
        ]
        jurisdictions = [Jurisdiction.RBI, Jurisdiction.RBI]

        parsed_docs, stats = await agent.parse_batch(raw_docs, jurisdictions)

        assert stats["total"] == 2
        assert stats["parsed"] == 2
        assert stats["failed"] == 0
        assert len(parsed_docs) == 2
        assert all(isinstance(doc, ParsedDocument) for doc in parsed_docs)
        assert stats["duration_seconds"] >= 0

    async def test_parse_batch_mixed_jurisdictions(self, agent: ParserAgent) -> None:
        """Test parsing batch with mixed jurisdictions."""
        raw_docs = [
            RawDocument(
                source_id="rbi",
                url="https://rbi.org.in/doc1",
                content_bytes=b"<html><body>RBI content</body></html>",
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 15),
                http_status=200,
            ),
            RawDocument(
                source_id="sebi",
                url="https://sebi.gov.in/doc1",
                content_bytes=b"<html><body>SEBI content</body></html>",
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 15),
                http_status=200,
            ),
            RawDocument(
                source_id="fda",
                url="https://fda.gov/doc1",
                content_bytes=b"<html><body>FDA content</body></html>",
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 15),
                http_status=200,
            ),
        ]
        jurisdictions = [Jurisdiction.RBI, Jurisdiction.SEBI, Jurisdiction.FDA]

        parsed_docs, stats = await agent.parse_batch(raw_docs, jurisdictions)
        assert stats["total"] == 3
        assert stats["parsed"] == 3
        assert len(parsed_docs) == 3

    async def test_parse_batch_continues_on_error(self, agent: ParserAgent) -> None:
        """Test batch parsing continues on individual failures."""
        raw_docs = [
            RawDocument(
                source_id="test",
                url="https://example.com/good1",
                content_bytes=b"<html><body>Good content 1</body></html>",
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 15),
                http_status=200,
            ),
            RawDocument(
                source_id="test",
                url="https://example.com/good2",
                content_bytes=b"<html><body>Good content 2</body></html>",
                headers={"Content-Type": "text/html"},
                fetched_at=datetime(2024, 1, 15),
                http_status=200,
            ),
        ]
        jurisdictions = [Jurisdiction.RBI, Jurisdiction.RBI]

        # Mock one parse to fail
        original_parse = agent.parse

        async def mock_parse(doc, jur):
            if "good1" in doc.url:
                raise Exception("Simulated parse error")
            return await original_parse(doc, jur)

        with patch.object(agent, "parse", side_effect=mock_parse):
            parsed_docs, stats = await agent.parse_batch(raw_docs, jurisdictions)

        assert stats["total"] == 2
        assert stats["parsed"] == 1
        assert stats["failed"] == 1
        assert len(stats["errors"]) == 1
        assert len(parsed_docs) == 1

    async def test_parse_batch_empty(self, agent: ParserAgent) -> None:
        """Test parsing empty batch."""
        parsed_docs, stats = await agent.parse_batch([], [])
        assert stats["total"] == 0
        assert stats["parsed"] == 0
        assert stats["failed"] == 0
        assert len(parsed_docs) == 0

    def test_parse_batch_length_mismatch(self, agent: ParserAgent) -> None:
        """Test parse_batch raises on length mismatch."""
        raw_docs = [
            RawDocument(
                url="https://example.com/1",
                content_bytes=b"",
                headers={},
                fetched_at=datetime(2024, 1, 15),
                source_id="test",
                http_status=200,
            )
        ]
        jurisdictions = [Jurisdiction.RBI, Jurisdiction.SEBI]

        with pytest.raises(ValueError, match="same length"):
            asyncio.run(agent.parse_batch(raw_docs, jurisdictions))

    def test_semaphore_concurrency_limit(self, agent: ParserAgent) -> None:
        """Test semaphore limits concurrent operations."""
        assert agent._semaphore._value == 2  # max_concurrent=2

    async def test_doc_id_deterministic(self, agent: ParserAgent) -> None:
        """Test doc_id is deterministic for same URL and timestamp."""
        raw_doc = RawDocument(
            url="https://example.com/doc",
            content_bytes=b"<html><body>Content</body></html>",
            headers={"Content-Type": "text/html"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_id="test",
            http_status=200,
        )

        result1 = await agent.parse(raw_doc, Jurisdiction.RBI)
        result2 = await agent.parse(raw_doc, Jurisdiction.RBI)

        assert result1.doc_id == result2.doc_id

    async def test_different_urls_different_ids(self, agent: ParserAgent) -> None:
        """Test different URLs produce different doc_ids."""
        raw_doc1 = RawDocument(
            url="https://example.com/doc1",
            content_bytes=b"<html><body>Content 1</body></html>",
            headers={"Content-Type": "text/html"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_id="test",
            http_status=200,
        )
        raw_doc2 = RawDocument(
            url="https://example.com/doc2",
            content_bytes=b"<html><body>Content 2</body></html>",
            headers={"Content-Type": "text/html"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_id="test",
            http_status=200,
        )

        result1 = await agent.parse(raw_doc1, Jurisdiction.RBI)
        result2 = await agent.parse(raw_doc2, Jurisdiction.RBI)

        assert result1.doc_id != result2.doc_id

    async def test_different_timestamps_different_ids(self, agent: ParserAgent) -> None:
        """Test same URL with different timestamps produce different doc_ids."""
        raw_doc1 = RawDocument(
            url="https://example.com/doc",
            content_bytes=b"<html><body>Content</body></html>",
            headers={"Content-Type": "text/html"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_id="test",
            http_status=200,
        )
        raw_doc2 = RawDocument(
            url="https://example.com/doc",
            content_bytes=b"<html><body>Content</body></html>",
            headers={"Content-Type": "text/html"},
            fetched_at=datetime(2024, 1, 16, 12, 0, 0),
            source_id="test",
            http_status=200,
        )

        result1 = await agent.parse(raw_doc1, Jurisdiction.RBI)
        result2 = await agent.parse(raw_doc2, Jurisdiction.RBI)

        assert result1.doc_id != result2.doc_id


class TestParserAgentIntegration:
    """Integration tests for ParserAgent with real fixtures."""

    async def test_parse_rbi_notification_fixture(self) -> None:
        """Test parsing RBI notification with real fixture."""
        fixture_path = FIXTURES_DIR / "rbi_notification.html"
        if not fixture_path.exists():
            pytest.skip("RBI fixture not found")

        html_bytes = fixture_path.read_bytes()
        raw_doc = RawDocument(
            url="https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345",
            content_bytes=html_bytes,
            headers={"Content-Type": "text/html; charset=utf-8"},
            fetched_at=datetime(2024, 1, 15, 12, 0, 0),
            source_id="rbi_notifications",
            http_status=200,
        )

        agent = ParserAgent()
        result = await agent.parse(raw_doc, Jurisdiction.RBI)

        assert result is not None
        assert "Master Direction" in result.title or "Investment Portfolio" in result.title
        assert "DBR.No.BP.BC.45" in result.body_text
        assert "15 January 2024" in result.body_text
        assert result.reference_number is not None
        assert "RBI/2024" in result.reference_number or "DBR" in result.reference_number
        assert result.document_type is not None
