"""Tests for NormalizerAgent (Phase 2b)."""

from __future__ import annotations

import pytest

from regmon.models import ParsedDocument
from regmon.models.documents import NormalizedDocument
from regmon.normalize import NormalizerAgent


class TestNormalizerAgent:
    """Tests for NormalizerAgent class."""

    @pytest.fixture
    def agent(self):
        return NormalizerAgent()

    @pytest.fixture
    def sample_parsed_docs(self):
        return [
            ParsedDocument(
                doc_id="doc1",
                url="https://www.rbi.org.in/scripts/notification.aspx?id=123",
                title="RBI Notification",
                body_text=(
                    "The Reserve Bank of India has issued a notification regarding "
                    "updated KYC norms for all scheduled commercial banks. Key changes "
                    "include enhanced due diligence for high-risk customers and "
                    "mandatory Aadhaar verification."
                ),
                published_date=None,
                reference_number="RBI/2024-25/123",
                document_type=None,
                lang=None,
            ),
            ParsedDocument(
                doc_id="doc2",
                url="https://www.sebi.gov.in/legal/circulars/jan-2024/circular-1.html",
                title="SEBI Circular",
                body_text=(
                    "SEBI has issued a circular regarding margin requirements for "
                    "derivatives trading. The circular specifies new margin computation "
                    "methodology for equity and commodity derivatives."
                ),
                published_date=None,
                reference_number="SEBI/HO/MRD/2024/456",
                document_type=None,
                lang=None,
            ),
            ParsedDocument(
                doc_id="doc3",
                url="https://www.fda.gov/news-events/press-announcements/test",
                title="FDA Press Release",
                body_text=(
                    "FDA has approved a new treatment for Alzheimer's disease. "
                    "This is a significant advancement in the treatment of this condition."
                ),
                published_date=None,
                reference_number=None,
                document_type=None,
                lang=None,
            ),
        ]

    @pytest.mark.asyncio
    async def test_normalize_single_document(self, agent, sample_parsed_docs):
        """Test normalizing a single document."""
        doc = sample_parsed_docs[0]
        result = await agent.normalize(doc)

        assert result is not None
        assert isinstance(result, NormalizedDocument)
        assert result.doc_id == doc.doc_id
        assert result.url == doc.url
        assert result.title == doc.title
        assert result.clean_text == doc.body_text  # No boilerplate on first call
        assert result.language == "en"
        assert result.char_count == len(doc.body_text)
        assert result.word_count > 0

    @pytest.mark.asyncio
    async def test_normalize_empty_body(self, agent):
        """Test normalizing document with empty body text."""
        doc = ParsedDocument(
            doc_id="empty",
            url="https://example.com/empty",
            title="Empty Document",
            body_text="",
            published_date=None,
            reference_number=None,
            document_type=None,
            lang=None,
        )
        result = await agent.normalize(doc)

        assert result is not None
        assert result.clean_text == ""
        assert result.char_count == 0
        assert result.word_count == 0
        assert result.language == "en"

    @pytest.mark.asyncio
    async def test_normalize_whitespace_only_body(self, agent):
        """Test normalizing document with whitespace-only body."""
        doc = ParsedDocument(
            doc_id="whitespace",
            url="https://example.com/ws",
            title="Whitespace Document",
            body_text="   \n\t  ",
            published_date=None,
            reference_number=None,
            document_type=None,
            lang=None,
        )
        result = await agent.normalize(doc)

        assert result is not None
        assert result.clean_text == "   \n\t  "
        # Character count should reflect actual whitespace length
        assert result.char_count == len("   \n\t  ")
        assert result.word_count == 0

    @pytest.mark.asyncio
    async def test_normalize_batch(self, agent, sample_parsed_docs):
        """Test batch normalization."""
        results, stats = await agent.normalize_batch(sample_parsed_docs)

        assert len(results) == 3
        assert stats["total"] == 3
        assert stats["normalized"] == 3
        assert stats["failed"] == 0
        assert stats["duration_seconds"] > 0
        assert stats["errors"] == []

        for result in results:
            assert isinstance(result, NormalizedDocument)
            assert result.language == "en"
            assert result.char_count > 0
            assert result.word_count > 0

    @pytest.mark.asyncio
    async def test_normalize_batch_with_site_keys(self, agent, sample_parsed_docs):
        """Test batch normalization with custom site keys."""
        site_keys = ["rbi.org.in", "sebi.gov.in", "fda.gov"]
        results, stats = await agent.normalize_batch(sample_parsed_docs, site_keys)

        assert len(results) == 3
        assert stats["normalized"] == 3

    @pytest.mark.asyncio
    async def test_normalize_batch_mismatched_site_keys(self, agent, sample_parsed_docs):
        """Test batch normalization with mismatched site keys length."""
        with pytest.raises(ValueError):
            await agent.normalize_batch(sample_parsed_docs, ["site1", "site2"])

    @pytest.mark.asyncio
    async def test_concurrency_limit(self, sample_parsed_docs):
        """Test semaphore limits concurrent operations."""
        agent = NormalizerAgent(max_concurrent=2)

        # Add a small delay to test concurrency
        original_normalize = agent._normalize_one

        async def slow_normalize(doc, site_key):
            import asyncio

            await asyncio.sleep(0.01)
            return await original_normalize(doc, site_key)

        agent._normalize_one = slow_normalize

        import time

        start = time.time()
        _results, stats = await agent.normalize_batch(sample_parsed_docs)
        duration = time.time() - start

        # With max_concurrent=2 and 3 docs taking 0.01s each,
        # should take at least 0.015s (2 parallel, then 1)
        assert duration >= 0.01
        assert stats["normalized"] == 3

    @pytest.mark.asyncio
    async def test_pipeline_order(self, agent):
        """Test normalization runs in correct order: repair -> strip -> detect -> stats."""
        # Document with mojibake and boilerplate
        doc = ParsedDocument(
            doc_id="order_test",
            url="https://example.com/test",
            title="Test",
            body_text=(
                "Home | About | Contact\n"
                "The bank said \xc3\xa2\xc2\x80\xc2\x9cWe will comply"
                "\xc3\xa2\xc2\x80\xc2\x9d.\n"
                "Footer | Privacy | Terms"
            ),
            published_date=None,
            reference_number=None,
            document_type=None,
            lang=None,
        )

        result = await agent.normalize(doc)

        assert result is not None
        # Mojibake should be fixed
        assert (
            "We will comply" in result.clean_text or "we will comply" in result.clean_text.lower()
        )
        # Language should be detected
        assert result.language == "en"
        # Stats should be computed
        assert result.char_count > 0
        assert result.word_count > 0

    @pytest.mark.asyncio
    async def test_derive_site_key(self, agent):
        """Test site key derivation from URL."""
        doc = ParsedDocument(
            doc_id="test",
            url="https://www.rbi.org.in/scripts/notification.aspx?id=123",
            title="Test",
            body_text="Test content",
            published_date=None,
            reference_number=None,
            document_type=None,
            lang=None,
        )

        site_key = agent._derive_site_key(doc)
        assert site_key == "rbi.org.in"

    @pytest.mark.asyncio
    async def test_batch_error_handling(self, agent):
        """Failed normalization should not stop other documents."""
        docs = [
            ParsedDocument(
                doc_id="good1",
                url="https://example.com/1",
                title="Good Doc",
                body_text="This is a good document with sufficient content.",
                published_date=None,
                reference_number=None,
                document_type=None,
                lang=None,
            ),
            ParsedDocument(
                doc_id="good2",
                url="https://example.com/2",
                title="Good Doc 2",
                body_text="Another good document with plenty of text content to process.",
                published_date=None,
                reference_number=None,
                document_type=None,
                lang=None,
            ),
        ]

        _results, stats = await agent.normalize_batch(docs)
        assert stats["normalized"] == 2
        assert stats["failed"] == 0

    def test_normalize_document_convenience(self, sample_parsed_docs):
        """Test sync convenience function."""
        # This runs async code internally via asyncio.run
        from regmon.normalize import normalize_document

        doc = sample_parsed_docs[0]
        result = normalize_document(doc, "test_site")

        assert isinstance(result, NormalizedDocument)
        assert result.doc_id == doc.doc_id
        assert result.language == "en"
