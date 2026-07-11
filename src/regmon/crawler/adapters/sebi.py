"""SEBI (Securities and Exchange Board of India) source adapter.

Covers:
- Legal Circulars: https://www.sebi.gov.in/legal/circulars.html
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urljoin

from regmon.crawler.adapters.base import BaseAdapter
from regmon.crawler.types import FetchResult, RemoteEntry


class SEBIAdapter(BaseAdapter):
    """Adapter for SEBI legal circulars."""

    DATE_PATTERNS: ClassVar[list[str]] = [
        r"\b(\d{1,2}\s+\w+\s+\d{4})\b",
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]

    # Ref pattern: SEBI/HO/IMD/IMD-PoD-1/P/CIR/2024/123
    REF_PATTERN: ClassVar = re.compile(r"\b(SEBI/[A-Z0-9./-]+(?:/\d{4}/\d+)?)\b")

    async def list_entries(self) -> AsyncIterator[RemoteEntry]:
        """List entries from SEBI circulars listing."""
        max_pages = self.crawl_policy.get("max_pages", 5)
        listing_url = self.source.listing_url
        if not listing_url:
            return

        for page in range(1, max_pages + 1):
            page_url = f"{listing_url}?page={page}" if page > 1 else listing_url

            soup = await self._fetch_listing_page(page_url)
            if not soup:
                break

            # SEBI circulars - look for table rows or card elements
            for row in soup.select("table tr, .circular-item, .legal-circular"):
                link, date_text, title_text = self._extract_from_row(row)
                if not link:
                    continue

                url = urljoin(self.base_url, link["href"])
                published = self._parse_date(date_text)

                if self.since and published and published < self.since:
                    continue

                ref = self._extract_reference(title_text) or self._extract_reference(date_text)

                yield RemoteEntry(
                    url=url,
                    title=title_text,
                    published_date=published,
                    metadata={
                        "reference_number": ref,
                        "document_type": "CIRCULAR",
                    },
                )

    def _extract_from_row(self, row) -> tuple | tuple[None, str, str]:
        """Extract link, date, title from a row/card."""
        if row.name == "tr":
            cells = row.find_all("td")
            if len(cells) < 2:
                return (None, "", "")
            date_text = cells[0].get_text(strip=True)
            title_text = cells[1].get_text(strip=True)
            link = cells[1].find("a", href=True)
            return (link, date_text, title_text)
        else:
            # Card/div format
            date_el = row.select_one(".date, .circular-date, time")
            title_el = row.select_one(".title, .circular-title, h3, h4, a")
            date_text = date_el.get_text(strip=True) if date_el else ""
            title_text = title_el.get_text(strip=True) if title_el else ""
            link = (
                title_el
                if title_el and title_el.name == "a"
                else title_el.find("a", href=True) if title_el else None
            )
            return (link, date_text, title_text)

    async def fetch_entry(self, entry: RemoteEntry) -> FetchResult:
        """Fetch full circular page."""
        return await self.fetcher.fetch(entry.url)
