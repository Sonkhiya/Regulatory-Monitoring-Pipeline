"""RBI (Reserve Bank of India) source adapter.

Covers:
- Notifications: https://www.rbi.org.in/Scripts/NotificationUser.aspx
- Press Releases: https://www.rbi.org.in/Scripts/BS_PressReleaseDisplay.aspx
"""

from __future__ import annotations

import re
from collections.abc import AsyncIterator
from typing import ClassVar
from urllib.parse import urljoin

from regmon.crawler.adapters.base import AdapterContext, BaseAdapter
from regmon.crawler.types import FetchResult, RemoteEntry


class RBIAdapter(BaseAdapter):
    """Adapter for RBI notifications and press releases."""

    DATE_PATTERNS: ClassVar[list[str]] = [
        r"\b(\d{1,2}\s+\w+\s+\d{4})\b",
        r"\b(\d{2}/\d{2}/\d{4})\b",
        r"\b(\d{4}-\d{2}-\d{2})\b",
    ]

    # Ref pattern: DBR.No.BP.BC.83/21.04.048/2023-24
    REF_PATTERN: ClassVar = re.compile(
        r"\b([A-Z]{2,}\.\w+(?:\.\w+)*/\d+(?:\.\d+)*(?:/\d{2,4}(?:-\d{2,4})?)?)\b"
    )

    def __init__(self, context: AdapterContext):
        # Override base_url based on source type
        base_url = "https://www.rbi.org.in"
        if "press" in context.source.id:
            base_url = "https://www.rbi.org.in"
        super().__init__(
            AdapterContext(
                source=context.source,
                fetcher=context.fetcher,
                base_url=base_url,
                since=context.since,
                crawl_policy=context.crawl_policy,
            )
        )

    async def list_entries(self) -> AsyncIterator[RemoteEntry]:
        """List entries from RBI notifications or press releases."""
        max_pages = self.crawl_policy.get("max_pages", 3)

        if "notification" in self.source.id:
            async for entry in self._list_notifications(max_pages):
                yield entry
        elif "press" in self.source.id:
            async for entry in self._list_press_releases(max_pages):
                yield entry

    async def _list_notifications(self, max_pages: int) -> AsyncIterator[RemoteEntry]:
        listing_url = self.source.listing_url
        if not listing_url:
            return

        for page in range(1, max_pages + 1):
            page_url = f"{listing_url}?page={page}" if page > 1 else listing_url

            soup = await self._fetch_listing_page(page_url)
            if not soup:
                break

            # RBI notifications table: Date | Subject | Department | Circular No.
            for row in soup.select("table tr"):
                cells = row.find_all("td")
                if len(cells) < 3:
                    continue

                date_text = cells[0].get_text(strip=True)
                subject = cells[1].get_text(strip=True)
                dept = cells[2].get_text(strip=True) if len(cells) > 2 else ""
                ref = cells[3].get_text(strip=True) if len(cells) > 3 else ""

                link = cells[1].find("a", href=True)
                if not link:
                    continue

                url = urljoin(self.base_url, str(link["href"]))
                published = self._parse_date(date_text)

                if self.since and published and published < self.since:
                    continue

                metadata = {
                    "department": dept,
                    "reference_number": ref or self._extract_reference(subject),
                    "document_type": "NOTIFICATION",
                }

                yield RemoteEntry(
                    url=url,
                    title=subject,
                    published_date=published,
                    metadata=metadata,
                )

    async def _list_press_releases(self, max_pages: int) -> AsyncIterator[RemoteEntry]:
        listing_url = self.source.listing_url
        if not listing_url:
            return

        for page in range(1, max_pages + 1):
            page_url = f"{listing_url}?page={page}" if page > 1 else listing_url

            soup = await self._fetch_listing_page(page_url)
            if not soup:
                break

            # Press releases - try multiple selectors
            for item in soup.select(".press-release, .pr-item, table tr, .content-block"):
                # Handle table row format
                if item.name == "tr":
                    cells = item.find_all("td")
                    if len(cells) < 2:
                        continue
                    date_text = cells[0].get_text(strip=True)
                    title_text = cells[1].get_text(strip=True)
                    link = cells[1].find("a", href=True)
                else:
                    # Div/Card format
                    date_el = item.select_one(".date, .pr-date, time")
                    title_el = item.select_one(".title, .pr-title, h3, h4, a")
                    date_text = date_el.get_text(strip=True) if date_el else ""
                    title_text = title_el.get_text(strip=True) if title_el else ""
                    link = (
                        title_el
                        if title_el and title_el.name == "a"
                        else (title_el.find("a", href=True) if title_el else None)
                    )

                if not link:
                    continue

                url = urljoin(self.base_url, str(link["href"]))
                published = self._parse_date(date_text)

                if self.since and published and published < self.since:
                    continue

                yield RemoteEntry(
                    url=url,
                    title=title_text,
                    published_date=published,
                    metadata={"document_type": "PRESS_RELEASE"},
                )

    async def fetch_entry(self, entry: RemoteEntry) -> FetchResult:
        """Fetch full notification/press release page."""
        return await self.fetcher.fetch(entry.url)
