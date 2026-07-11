"""Base adapter interface for regulatory source crawlers (plan.md §5.2)."""

from __future__ import annotations

import re
from abc import ABC, abstractmethod
from collections.abc import AsyncIterator
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any, ClassVar
from urllib.parse import urljoin

from bs4 import BeautifulSoup

from regmon.config.source_registry import RegulatorySource
from regmon.crawler.fetcher import AsyncFetcher
from regmon.crawler.types import FetchResult, RemoteEntry

if TYPE_CHECKING:
    from regmon.models import RawDocument


@dataclass(slots=True)
class AdapterContext:
    """Runtime context passed to adapters."""

    source: RegulatorySource
    fetcher: AsyncFetcher
    base_url: str
    since: datetime | None = None
    crawl_policy: dict[str, Any] | None = None

    def __post_init__(self):
        if self.crawl_policy is None:
            self.crawl_policy = {}


class BaseAdapter(ABC):
    """Abstract base class for source adapters.

    Each adapter implements:
    - list_entries(): Async iterator yielding RemoteEntry objects
    - fetch_entry(): Fetch full document for a RemoteEntry (can use default)
    - result_to_raw_document(): Convert FetchResult to RawDocument
    """

    # Override in subclasses for jurisdiction-specific patterns
    DATE_PATTERNS: ClassVar[list[str]] = [
        r"\b(\d{1,2}\s+\w+\s+\d{4})\b",  # 15 January 2024
        r"\b(\d{2}/\d{2}/\d{4})\b",  # 15/01/2024
        r"\b(\d{4}-\d{2}-\d{2})\b",  # 2024-01-15
    ]
    REF_PATTERN: ClassVar[re.Pattern | None] = None  # Subclasses should define specific patterns

    def __init__(self, context: AdapterContext):
        self._context = context

    @property
    def source(self) -> RegulatorySource:
        return self._context.source

    @property
    def fetcher(self) -> AsyncFetcher:
        return self._context.fetcher

    @property
    def base_url(self) -> str:
        return self._context.base_url

    @property
    def since(self) -> datetime | None:
        return self._context.since

    @property
    def crawl_policy(self) -> dict[str, Any]:
        return self._context.crawl_policy or {}

    @abstractmethod
    async def list_entries(self) -> AsyncIterator[RemoteEntry]:
        """Yield discovered entries from the source listing/feed.

        Should respect self.since for incremental crawls and
        self.crawl_policy for limits (max_pages, max_items, etc.).
        """
        # Type hint for async generator - pragma: no cover
        if False:
            yield RemoteEntry(url="")
        # pragma: no cover

    async def fetch_entry(self, entry: RemoteEntry) -> FetchResult:
        """Fetch the full document for a RemoteEntry.

        Default implementation uses the shared AsyncFetcher.
        Override for special handling (auth, redirects, etc.).
        """
        return await self.fetcher.fetch(entry.url)

    def result_to_raw_document(self, result: FetchResult, entry: RemoteEntry) -> RawDocument:
        """Convert a FetchResult and RemoteEntry to a RawDocument.

        Adapters can override to add jurisdiction-specific metadata extraction.
        """
        from regmon.models import RawDocument

        return RawDocument(
            source_id=self.source.id,
            url=result.url,
            fetched_at=datetime.now(timezone.utc),
            http_status=result.status,
            content_bytes=result.content or b"",
            headers=result.headers,
            etag=result.etag,
            last_modified=result.last_modified,
        )

    # --- Shared helpers ---

    def _parse_date(self, text: str) -> datetime | None:
        """Parse date from text using jurisdiction-specific patterns."""
        for pattern in self.DATE_PATTERNS:
            match = re.search(pattern, text)
            if match:
                date_str = match.group(1)
                for fmt in ("%d %B %Y", "%d/%m/%Y", "%Y-%m-%d", "%d-%m-%Y"):
                    try:
                        return datetime.strptime(date_str, fmt).replace(tzinfo=timezone.utc)
                    except ValueError:
                        continue
        return None

    def _extract_reference(self, text: str) -> str | None:
        """Extract reference number using subclass pattern."""
        if self.REF_PATTERN:
            match = self.REF_PATTERN.search(text)
            if match:
                return match.group(1)
        return None

    def _make_absolute_url(self, href: str) -> str:
        return urljoin(self.base_url, href)

    async def _fetch_listing_page(self, url: str) -> BeautifulSoup | None:
        """Fetch and parse a listing page."""
        try:
            resp = await self.fetcher._client.get(url, timeout=30.0)
            if resp.status_code == 200:
                return BeautifulSoup(resp.content, "html.parser")
        except Exception:
            pass
        return None
