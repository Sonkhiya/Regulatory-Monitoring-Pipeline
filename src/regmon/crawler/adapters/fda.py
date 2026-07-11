"""FDA (U.S. Food and Drug Administration) source adapter.

Covers:
- Press Releases RSS: https://www.fda.gov/about-fda/fda-press-releases/press-releases-rss
- Federal Register API: https://www.federalregister.gov/api/v1/articles.json
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from datetime import datetime, timezone
from typing import ClassVar

import feedparser

from regmon.crawler.adapters.base import BaseAdapter
from regmon.crawler.types import FetchResult, RemoteEntry


class FDAAdapter(BaseAdapter):
    """Adapter for FDA press releases (RSS) and Federal Register (JSON API)."""

    DATE_PATTERNS: ClassVar[list[str]] = [
        r"\b(\w+\s+\d{1,2},?\s+\d{4})\b",  # January 15, 2024
        r"\b(\d{4}-\d{2}-\d{2})\b",  # 2024-01-15
    ]

    REF_PATTERN: ClassVar = re.compile(r"\b(FDA-\d{4}-\d+)\b")

    async def list_entries(self) -> AsyncIterator[RemoteEntry]:
        """List entries from FDA RSS feed or Federal Register API."""
        feed_url = self.source.feed_url
        if not feed_url:
            return

        max_items = self.crawl_policy.get("max_items", 50)

        if "rss" in feed_url.lower() or "xml" in feed_url.lower():
            async for entry in self._list_from_rss(feed_url, max_items):
                yield entry
        elif "federalregister" in feed_url.lower() or "api" in feed_url.lower():
            async for entry in self._list_from_federal_register(feed_url, max_items):
                yield entry

    async def _list_from_rss(self, feed_url: str, max_items: int) -> AsyncIterator[RemoteEntry]:
        """Parse FDA press releases RSS feed."""
        import asyncio

        loop = asyncio.get_event_loop()
        feed = await loop.run_in_executor(None, feedparser.parse, feed_url)

        for item in feed.entries[:max_items]:
            title = item.get("title", "")
            link = item.get("link", "")
            published = self._parse_rss_date(item)

            if self.since and published and published < self.since:
                continue

            ref = self._extract_reference(title)

            yield RemoteEntry(
                url=link,
                title=title,
                published_date=published,
                summary=item.get("summary", ""),
                metadata={
                    "reference_number": ref,
                    "document_type": "PRESS_RELEASE",
                    "feed_id": item.get("id", ""),
                },
            )

    async def _list_from_federal_register(
        self, api_url: str, max_items: int
    ) -> AsyncIterator[RemoteEntry]:
        """Parse Federal Register JSON API for FDA rules."""
        # Build API URL with params
        base_url = api_url.split("?")[0] if "?" in api_url else api_url
        fetch_url = (
            f"{base_url}?"
            f"conditions%5Bpublication_date%5D%5Bgte%5D="
            f"{datetime.now().strftime('%Y-%m-%d')}"
            f"&conditions%5Bagencies%5D%5B%5D=food-and-drug-administration"
            f"&order=newest&per_page={max_items}"
        )

        async with self.fetcher._client.stream("GET", fetch_url) as resp:
            if resp.status_code != 200:
                return
            data = await resp.json()

        for item in data.get("results", [])[:max_items]:
            title = item.get("title", "")
            url = item.get("html_url", "") or item.get("pdf_url", "")
            pub_date_str = item.get("publication_date", "")
            published = self._parse_fr_date(pub_date_str)

            if self.since and published and published < self.since:
                continue

            doc_type = item.get("type", "")
            ref = item.get("document_number", "")

            yield RemoteEntry(
                url=url,
                title=title,
                published_date=published,
                summary=item.get("abstract", ""),
                metadata={
                    "reference_number": ref,
                    "document_type": doc_type.upper() if doc_type else "REGULATION",
                    "fr_citation": item.get("citation", ""),
                    "agencies": [a.get("name", "") for a in item.get("agencies", [])],
                },
            )

    def _parse_rss_date(self, item) -> datetime | None:
        """Parse date from RSS item."""
        for field in ("published_parsed", "updated_parsed", "created_parsed"):
            if item.get(field):
                try:
                    return datetime(*item[field][:6]).replace(tzinfo=timezone.utc)
                except Exception:
                    pass
        # Fallback to string parsing
        for field in ("published", "updated", "created"):
            if item.get(field):
                parsed = self._parse_date(item[field])
                if parsed:
                    return parsed
        return None

    def _parse_fr_date(self, date_str: str) -> datetime | None:
        """Parse Federal Register date format."""
        for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S%z", "%Y-%m-%dT%H:%M:%S"):
            try:
                dt = datetime.strptime(date_str, fmt)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                return dt
            except ValueError:
                continue
        return None

    async def fetch_entry(self, entry: RemoteEntry) -> FetchResult:
        """Fetch full document (press release page or FR page)."""
        return await self.fetcher.fetch(entry.url)
