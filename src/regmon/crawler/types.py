"""Shared types for the crawler module (plan.md §5.2)."""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import datetime
from typing import Any


@dataclass(slots=True)
class RemoteEntry:
    """A single entry discovered from a source listing (HTML page or feed).

    Adapters return iterables of these from ``list_entries()``.
    The fetcher uses ``url`` + optional conditional headers to perform
    a conditional GET (304 handling).
    """

    url: str
    """Absolute URL to fetch the full document."""
    title: str | None = None
    """Title extracted from the listing/feed (may be refined on full fetch)."""
    published_date: datetime | None = None
    """Publication date if available from the listing/feed."""
    summary: str | None = None
    """Short summary/excerpt from the listing/feed."""
    metadata: dict[str, Any] | None = None
    """Adapter-specific payload (e.g. reference_number, document_type hint)."""

    def __post_init__(self) -> None:
        if self.metadata is None:
            self.metadata = {}


@dataclass(slots=True)
class FetchResult:
    """Result of a fetch attempt (success or conditional 304)."""

    url: str
    status: int
    """HTTP status code (200, 304, 4xx, 5xx)."""
    content: bytes | None
    """Response body (None for 304)."""
    headers: dict[str, str]
    """Response headers (lowercased keys)."""
    etag: str | None = None
    """ETag from response (for next conditional request)."""
    last_modified: str | None = None
    """Last-Modified from response (for next conditional request)."""
    from_cache: bool = False
    """True if response was served from local cache (304)."""

    @property
    def is_not_modified(self) -> bool:
        """True if the resource has not changed (304)."""
        return self.status == 304

    @property
    def is_success(self) -> bool:
        """True if fetch returned new content (2xx)."""
        return 200 <= self.status < 300 and not self.is_not_modified

    @property
    def content_hash(self) -> str:
        """SHA-256 hash of content (empty string for None)."""
        if self.content is None:
            return ""
        return hashlib.sha256(self.content).hexdigest()
