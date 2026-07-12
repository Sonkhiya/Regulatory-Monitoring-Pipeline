"""Unit tests for crawler adapters (Phase 2 Crawler)."""

from __future__ import annotations

from datetime import datetime, timezone

import httpx
import pytest

from regmon.config.source_registry import RegulatorySource
from regmon.crawler.adapters import create_adapter
from regmon.crawler.adapters.eu_ai_act import EUAIActAdapter
from regmon.crawler.adapters.fda import FDAAdapter
from regmon.crawler.adapters.rbi import RBIAdapter
from regmon.crawler.adapters.sebi import SEBIAdapter
from regmon.crawler.fetcher import AsyncFetcher
from regmon.crawler.rate_limiter import RateLimiter
from regmon.crawler.robots_cache import RobotsCache
from regmon.crawler.types import RemoteEntry


def _make_source(
    id: str,
    adapter: str,
    listing_url: str = "",
    feed_url: str = "",
    crawl_policy: dict | None = None,
) -> RegulatorySource:
    """Helper to create a RegulatorySource for testing."""
    # Map adapter to correct jurisdiction
    jurisdiction_map = {
        "rbi": "RBI",
        "sebi": "SEBI",
        "fda": "FDA",
        "eu_ai_act": "EU_AI_ACT",
    }
    jurisdiction = jurisdiction_map.get(adapter, "RBI")

    return RegulatorySource(
        id=id,
        jurisdiction=jurisdiction,
        name=f"Test {id}",
        listing_url=listing_url,
        feed_url=feed_url,
        adapter=adapter,
        crawl_policy=crawl_policy or {},
    )


async def _make_fetcher(mock_transport: httpx.MockTransport) -> AsyncFetcher:
    """Create AsyncFetcher with mock transport for testing."""
    client = httpx.AsyncClient(transport=mock_transport)
    return AsyncFetcher(
        client=client,
        rate_limiter=RateLimiter(rate_per_minute=1000, burst=100, jitter=0.0),
        robots_cache=RobotsCache(client, ttl_seconds=3600, failure_ttl=300),
        user_agent="RegMon-Test/1.0",
    )


class TestRBIAdapter:
    """Tests for RBIAdapter."""

    @pytest.mark.asyncio
    async def test_list_notifications(self, mock_transport: httpx.MockTransport):
        """list_entries yields notifications with correct fields."""
        source = _make_source(
            id="rbi_notifications",
            adapter="rbi",
            listing_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 notifications

        # Check first entry
        e = entries[0]
        assert e.url == "https://www.rbi.org.in/Scripts/NotificationUser.aspx?Id=12345&Mode=0"
        assert e.title == "Revision of Risk Weights for Residential Housing Loans"
        assert e.published_date is not None
        assert e.published_date == datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert e.metadata["document_type"] == "NOTIFICATION"
        assert e.metadata["reference_number"] == "DBR.No.BP.BC.83/21.04.048/2023-24"
        assert e.metadata["department"] == "Department of Regulation"

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_list_press_releases(self, mock_transport: httpx.MockTransport):
        """list_entries yields press releases with correct fields."""
        source = _make_source(
            id="rbi_press_releases",
            adapter="rbi",
            listing_url="https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 press releases

        e = entries[0]
        assert e.url == "https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx?prid=56789"
        assert "Governor" in e.title
        assert e.published_date == datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert e.metadata["document_type"] == "PRESS_RELEASE"

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_since_filters_old_entries(self, mock_transport: httpx.MockTransport):
        """since parameter filters out entries older than cutoff."""
        source = _make_source(
            id="rbi_notifications",
            adapter="rbi",
            listing_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        # since = Jan 9, 2024 - should exclude Jan 5, include Jan 10 and Jan 15
        since = datetime(2024, 1, 9, tzinfo=timezone.utc)
        adapter = create_adapter(source, fetcher, since=since)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        # Should only have Jan 15 and Jan 10 entries (2 entries)
        assert len(entries) == 2
        for e in entries:
            assert e.published_date >= since

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_max_pages_limit(self, mock_transport: httpx.MockTransport):
        """max_pages limits pagination."""
        source = _make_source(
            id="rbi_notifications",
            adapter="rbi",
            listing_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        count = 0
        async for _ in adapter.list_entries():
            count += 1

        # Page 1 has 3 entries, page 2 would have more but limited to 1 page
        assert count == 3

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_entry(self, mock_transport: httpx.MockTransport):
        """fetch_entry returns FetchResult with content."""
        source = _make_source(
            id="rbi_notifications",
            adapter="rbi",
            listing_url="https://www.rbi.org.in/Scripts/NotificationUser.aspx",
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        # First get an entry
        entry = None
        async for e in adapter.list_entries():
            entry = e
            break

        assert entry is not None
        result = await adapter.fetch_entry(entry)

        assert result.status == 200
        assert result.content is not None
        assert len(result.content) > 0

        await fetcher.close()


class TestSEBIAdapter:
    """Tests for SEBIAdapter."""

    @pytest.mark.asyncio
    async def test_list_circulars(self, mock_transport: httpx.MockTransport):
        """list_entries yields circulars with correct fields."""
        source = _make_source(
            id="sebi_circulars",
            adapter="sebi",
            listing_url="https://www.sebi.gov.in/legal/circulars.html",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 circulars

        e = entries[0]
        assert e.url == "https://www.sebi.gov.in/legal/circulars/jan-2024/circular-1.html"
        assert "REITs" in e.title
        assert e.published_date == datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert e.metadata["document_type"] == "CIRCULAR"
        assert "SEBI/HO/IMD" in e.metadata["reference_number"]

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_since_filters_old_entries(self, mock_transport: httpx.MockTransport):
        """since filters out older circulars."""
        source = _make_source(
            id="sebi_circulars",
            adapter="sebi",
            listing_url="https://www.sebi.gov.in/legal/circulars.html",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        since = datetime(2024, 1, 9, tzinfo=timezone.utc)  # Exclude Jan 5, include Jan 10, 15
        adapter = create_adapter(source, fetcher, since=since)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        # Should only have Jan 15 and Jan 10 (2 entries)
        assert len(entries) == 2
        for e in entries:
            assert e.published_date >= since

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_max_pages_limit(self, mock_transport: httpx.MockTransport):
        """max_pages limits pagination."""
        source = _make_source(
            id="sebi_circulars",
            adapter="sebi",
            listing_url="https://www.sebi.gov.in/legal/circulars.html",
            crawl_policy={"max_pages": 2},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        count = 0
        async for _ in adapter.list_entries():
            count += 1

        # Page 1 has 3, page 2 is empty
        assert count == 3

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_entry(self, mock_transport: httpx.MockTransport):
        """fetch_entry returns FetchResult with content."""
        source = _make_source(
            id="sebi_circulars",
            adapter="sebi",
            listing_url="https://www.sebi.gov.in/legal/circulars.html",
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entry = None
        async for e in adapter.list_entries():
            entry = e
            break

        assert entry is not None
        result = await adapter.fetch_entry(entry)

        assert result.status == 200
        assert result.content is not None

        await fetcher.close()


class TestFDAAdapter:
    """Tests for FDAAdapter."""

    @pytest.mark.asyncio
    async def test_list_rss_feed(self, mock_transport: httpx.MockTransport):
        """list_entries from RSS yields entries with summary and feed_id."""
        source = _make_source(
            id="fda_press_releases",
            adapter="fda",
            feed_url="https://www.fda.gov/about-fda/fda-press-releases/press-releases-rss",
            crawl_policy={"max_items": 10},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 RSS items

        e = entries[0]
        assert (
            e.url
            == "https://www.fda.gov/news-events/press-announcements/fda-approves-new-treatment-alzheimers-disease"
        )
        assert "Alzheimer" in e.title
        assert e.published_date is not None
        assert e.summary is not None
        assert len(e.summary) > 0
        assert e.metadata["document_type"] == "PRESS_RELEASE"
        assert "feed_id" in e.metadata

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_list_federal_register(self, mock_transport: httpx.MockTransport):
        """list_entries from Federal Register JSON yields entries with FR citation."""
        source = _make_source(
            id="fda_federal_register",
            adapter="fda",
            feed_url="https://www.federalregister.gov/api/v1/articles.json?conditions%5Bpublication_date%5D%5Bgte%5D=2024-01-01&conditions%5Bagencies%5D%5B%5D=food-and-drug-administration&order=newest&per_page=50",
            crawl_policy={"max_items": 10},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 FR items

        e = entries[0]
        assert (
            e.url
            == "https://www.federalregister.gov/documents/2024/01/15/2024-00123/food-and-drug-administration-guidance-for-industry-clinical-trial-diversity"
        )
        assert e.metadata["document_type"] == "NOTICE"
        assert e.metadata["fr_citation"] == "89 FR 2345"
        assert "agencies" in e.metadata
        assert "Food and Drug Administration" in e.metadata["agencies"]

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_since_filters_old_entries(self, mock_transport: httpx.MockTransport):
        """since filters out older entries from both RSS and FR."""
        source = _make_source(
            id="fda_press_releases",
            adapter="fda",
            feed_url="https://www.fda.gov/about-fda/fda-press-releases/press-releases-rss",
            crawl_policy={"max_items": 10},
        )
        fetcher = await _make_fetcher(mock_transport)
        since = datetime(2024, 1, 13, tzinfo=timezone.utc)  # After Jan 12, before Jan 15
        adapter = create_adapter(source, fetcher, since=since)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        # Should only have Jan 15 entry
        assert len(entries) == 1
        assert entries[0].published_date >= since

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_max_items_limit(self, mock_transport: httpx.MockTransport):
        """max_items limits total entries."""
        source = _make_source(
            id="fda_press_releases",
            adapter="fda",
            feed_url="https://www.fda.gov/about-fda/fda-press-releases/press-releases-rss",
            crawl_policy={"max_items": 2},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        count = 0
        async for _ in adapter.list_entries():
            count += 1

        assert count == 2

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_entry(self, mock_transport: httpx.MockTransport):
        """fetch_entry returns FetchResult with content."""
        source = _make_source(
            id="fda_press_releases",
            adapter="fda",
            feed_url="https://www.fda.gov/about-fda/fda-press-releases/press-releases-rss",
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entry = None
        async for e in adapter.list_entries():
            entry = e
            break

        assert entry is not None
        result = await adapter.fetch_entry(entry)

        assert result.status == 200
        assert result.content is not None

        await fetcher.close()


class TestEUAIActAdapter:
    """Tests for EUAIActAdapter."""

    @pytest.mark.asyncio
    async def test_list_newsroom(self, mock_transport: httpx.MockTransport):
        """list_entries yields news articles with summary and reference."""
        source = _make_source(
            id="eu_ai_act_newsroom",
            adapter="eu_ai_act",
            listing_url="https://artificial-intelligence-act.com/news/",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        assert len(entries) >= 3  # Fixture has 3 articles

        e = entries[0]
        assert e.url == "https://artificial-intelligence-act.com/news/article-1.html"
        assert "Classification" in e.title
        assert e.published_date == datetime(2024, 1, 15, tzinfo=timezone.utc)
        assert e.summary is not None
        assert "guidelines" in e.summary.lower()
        assert e.metadata["document_type"] == "NEWS"
        # First entry has no Article/Annex/Recital reference - that's OK
        # Check second entry which has "Article 5"
        assert entries[1].metadata["reference_number"] == "Article 5"

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_since_filters_old_entries(self, mock_transport: httpx.MockTransport):
        """since filters out older articles."""
        source = _make_source(
            id="eu_ai_act_newsroom",
            adapter="eu_ai_act",
            listing_url="https://artificial-intelligence-act.com/news/",
            crawl_policy={"max_pages": 1},
        )
        fetcher = await _make_fetcher(mock_transport)
        since = datetime(2024, 1, 9, tzinfo=timezone.utc)  # Exclude Jan 5, include Jan 10, 15
        adapter = create_adapter(source, fetcher, since=since)

        entries: list[RemoteEntry] = []
        async for entry in adapter.list_entries():
            entries.append(entry)

        # Should only have Jan 15 and Jan 10 (2 entries)
        assert len(entries) == 2
        for e in entries:
            assert e.published_date >= since

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_max_pages_limit(self, mock_transport: httpx.MockTransport):
        """max_pages limits pagination."""
        source = _make_source(
            id="eu_ai_act_newsroom",
            adapter="eu_ai_act",
            listing_url="https://artificial-intelligence-act.com/news/",
            crawl_policy={"max_pages": 2},
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        count = 0
        async for _ in adapter.list_entries():
            count += 1

        # Page 1 has 3, page 2 is empty
        assert count == 3

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_entry(self, mock_transport: httpx.MockTransport):
        """fetch_entry returns FetchResult with content."""
        source = _make_source(
            id="eu_ai_act_newsroom",
            adapter="eu_ai_act",
            listing_url="https://artificial-intelligence-act.com/news/",
        )
        fetcher = await _make_fetcher(mock_transport)
        adapter = create_adapter(source, fetcher)

        entry = None
        async for e in adapter.list_entries():
            entry = e
            break

        assert entry is not None
        result = await adapter.fetch_entry(entry)

        assert result.status == 200
        assert result.content is not None

        await fetcher.close()


class TestAdapterFactory:
    """Tests for adapter factory functions."""

    def test_registered_adapters(self):
        """All four adapters are registered."""
        from regmon.crawler.adapters import get_adapter_class

        assert get_adapter_class("rbi") is RBIAdapter
        assert get_adapter_class("sebi") is SEBIAdapter
        assert get_adapter_class("fda") is FDAAdapter
        assert get_adapter_class("eu_ai_act") is EUAIActAdapter
        assert get_adapter_class("unknown") is None

    @pytest.mark.asyncio
    async def test_create_adapter_unknown_raises(self, mock_transport: httpx.MockTransport):
        """create_adapter raises ValueError for unknown adapter."""
        source = _make_source(id="test", adapter="unknown")
        fetcher = await _make_fetcher(mock_transport)

        with pytest.raises(ValueError, match="Unknown adapter"):
            create_adapter(source, fetcher)

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_create_adapter_returns_correct_type(self, mock_transport: httpx.MockTransport):
        """create_adapter returns correct adapter instance."""
        for adapter_name, expected_class in [
            ("rbi", RBIAdapter),
            ("sebi", SEBIAdapter),
            ("fda", FDAAdapter),
            ("eu_ai_act", EUAIActAdapter),
        ]:
            source = _make_source(id=f"test_{adapter_name}", adapter=adapter_name)
            fetcher = await _make_fetcher(mock_transport)
            adapter = create_adapter(source, fetcher)
            assert isinstance(adapter, expected_class)
            await fetcher.close()
