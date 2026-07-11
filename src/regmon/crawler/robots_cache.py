"""Cached robots.txt parser with TTL (plan.md §5.2)."""

from __future__ import annotations

import asyncio
import time
import urllib.robotparser
from dataclasses import dataclass, field

import httpx


@dataclass(slots=True)
class _RobotsEntry:
    """Cached robots.txt entry with expiration."""

    parser: urllib.robotparser.RobotFileParser
    expires_at: float
    fetch_time: float = field(default_factory=time.monotonic)

    def is_expired(self) -> bool:
        return time.monotonic() >= self.expires_at


class RobotsCache:
    """Async robots.txt cache with per-host TTL and failed-fetch handling.

    - Fetches and parses robots.txt on first request per host.
    - Caches the parsed RobotFileParser for ``ttl_seconds``.
    - On fetch failure (4xx, 5xx, network error), allows all paths for that host
      for a short ``failure_ttl`` to avoid repeated failed fetches.
    - Thread-safe via asyncio.Lock per host.
    """

    def __init__(
        self,
        client: httpx.AsyncClient,
        ttl_seconds: float = 3600,
        failure_ttl: float = 300,
        user_agent: str = "RegMon/1.0",
    ) -> None:
        """
        Args:
            client: Shared httpx.AsyncClient for fetching robots.txt.
            ttl_seconds: Cache TTL for successful parses (default 1 hour).
            failure_ttl: Cache TTL for failed fetches (default 5 min).
            user_agent: User-Agent string to check against robots.txt rules.
        """
        if ttl_seconds <= 0:
            raise ValueError("ttl_seconds must be positive")
        if failure_ttl <= 0:
            raise ValueError("failure_ttl must be positive")

        self._client = client
        self._ttl = ttl_seconds
        self._failure_ttl = failure_ttl
        self._user_agent = user_agent
        self._cache: dict[str, _RobotsEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}

        # Pre-create a permissive parser for fail-open
        self._permissive_parser = urllib.robotparser.RobotFileParser()
        self._permissive_parser.parse(["User-agent: *", "Allow: /"])

    def _get_lock(self, host: str) -> asyncio.Lock:
        if host not in self._locks:
            self._locks[host] = asyncio.Lock()
        return self._locks[host]

    async def can_fetch(self, url: str) -> bool:
        """Check if ``url`` is allowed by the host's robots.txt.

        Returns ``True`` if allowed, ``False`` if disallowed, ``True`` on
        parse/fetch errors (fail-open with short cache).
        """
        parsed = httpx.URL(url)
        host = parsed.host
        if not host:
            return True

        lock = self._get_lock(host)
        async with lock:
            entry = self._cache.get(host)

            if entry and not entry.is_expired():
                return entry.parser.can_fetch(self._user_agent, url)

            # Need to fetch (or refetch)
            await self._fetch_and_cache(host)

            # Re-read after fetch
            entry = self._cache.get(host)
            if entry:
                return entry.parser.can_fetch(self._user_agent, url)

            # Should not happen, but fail-open
            return True

    async def _fetch_and_cache(self, host: str) -> None:
        """Fetch robots.txt for ``host`` and update cache."""
        robots_url = f"https://{host}/robots.txt"
        now = time.monotonic()
        expires_at = now + self._ttl
        failure_expires = now + self._failure_ttl

        parser = urllib.robotparser.RobotFileParser()
        parser.modified()

        try:
            resp = await self._client.get(
                robots_url,
                follow_redirects=True,
                timeout=10.0,
            )
            if resp.is_success:
                parser.parse(resp.text.splitlines())
                self._cache[host] = _RobotsEntry(parser=parser, expires_at=expires_at)
            else:
                # Non-success: fail-open with short TTL
                self._cache[host] = _RobotsEntry(
                    parser=self._permissive_parser, expires_at=failure_expires
                )
        except Exception:  # httpx.RequestError, asyncio.TimeoutError, etc.
            # Network error: fail-open with short TTL
            self._cache[host] = _RobotsEntry(
                parser=self._permissive_parser, expires_at=failure_expires
            )

    def clear(self, host: str | None = None) -> None:
        """Clear cache for ``host`` or all hosts if ``host`` is None."""
        if host:
            self._cache.pop(host, None)
            self._locks.pop(host, None)
        else:
            self._cache.clear()
            self._locks.clear()
