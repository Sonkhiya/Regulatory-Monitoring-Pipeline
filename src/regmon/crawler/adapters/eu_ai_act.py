"""EU AI Act Newsroom adapter.

Covers:
- EU AI Act Newsroom: https://artificial-intelligence-act.com/news/
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urljoin

from regmon.crawler.adapters.base import BaseAdapter
from regmon.crawler.types import FetchResult, RemoteEntry


class EUAIActAdapter(BaseAdapter):
    """Adapter for EU AI Act newsroom."""

    DATE_PATTERNS: ClassVar[list[str]] = [
        r"\b(\d{1,2}\s+\w+\s+\d{4})\b",
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]

    # Ref patterns: "Article 5", "Annex III", "Recital 12", etc.
    REF_PATTERN: ClassVar = re.compile(
        r"\b(Article\s+\d+[A-Z]?|Annex\s+[IVX]+|Recital\s+\d+)\b", re.IGNORECASE
    )

    async def list_entries(self) -> AsyncIterator[RemoteEntry]:
        """List entries from EU AI Act newsroom."""
        max_pages = self.crawl_policy.get("max_pages", 3)
        listing_url = self.source.listing_url
        if not listing_url:
            return

        for page in range(1, max_pages + 1):
            page_url = f"{listing_url}page/{page}/" if page > 1 else listing_url

            soup = await self._fetch_listing_page(page_url)
            if not soup:
                break

            # News articles in article cards
            for article in soup.select("article, .post, .news-item, .entry"):
                link = article.find("a", href=True)
                if not link:
                    continue

                url = urljoin(self.base_url, str(link["href"]))
                title = link.get_text(strip=True)

                # Try to find date
                date_el = article.select_one("time, .date, .post-date, .published")
                date_text = date_el.get_text(strip=True) if date_el else ""
                published = self._parse_date(date_text)

                if self.since and published and published < self.since:
                    continue

                # Extract description/summary
                summary_el = article.select_one(".excerpt, .summary, .description, p")
                summary = summary_el.get_text(strip=True) if summary_el else ""

                ref = self._extract_reference(title) or self._extract_reference(summary)

                yield RemoteEntry(
                    url=url,
                    title=title,
                    published_date=published,
                    summary=summary,
                    metadata={
                        "reference_number": ref,
                        "document_type": "NEWS",
                    },
                )

    async def fetch_entry(self, entry: RemoteEntry) -> FetchResult:
        """Fetch full news article."""
        return await self.fetcher.fetch(entry.url)
