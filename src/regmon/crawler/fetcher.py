"""Async HTTP fetcher with conditional GET, retry, and robots.txt (plan.md §5.2)."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from urllib.parse import urlparse

import httpx
from tenacity import (
    AsyncRetrying,
    retry_if_exception_type,
    stop_after_attempt,
    wait_exponential_jitter,
)

from regmon.crawler.rate_limiter import RateLimiter
from regmon.crawler.robots_cache import RobotsCache
from regmon.crawler.types import FetchResult


@dataclass(slots=True)
class _ConditionalHeaders:
    """ETag/Last-Modified headers for conditional requests."""

    etag: str | None = None
    last_modified: str | None = None

    def to_headers(self) -> dict[str, str]:
        h: dict[str, str] = {}
        if self.etag:
            h["If-None-Match"] = self.etag
        if self.last_modified:
            h["If-Modified-Since"] = self.last_modified
        return h


class AsyncFetcher:
    """High-level async fetcher with:

    - Per-host rate limiting (token bucket + jitter)
    - robots.txt compliance (cached)
    - Conditional GET (ETag/Last-Modified) with 304 handling
    - Exponential backoff retry with jitter
    - Configurable timeout and max redirects
    """

    def __init__(
        self,
        *,
        client: httpx.AsyncClient | None = None,
        rate_limiter: RateLimiter | None = None,
        robots_cache: RobotsCache | None = None,
        default_timeout: float = 30.0,
        max_redirects: int = 10,
        user_agent: str = "RegMon/1.0 (+https://github.com/regmon)",
        respect_robots: bool = True,
        max_retries: int = 3,
        retry_base_delay: float = 1.0,
        retry_max_delay: float = 30.0,
    ) -> None:
        """
        Args:
            client: Shared httpx.AsyncClient (created if not provided).
            rate_limiter: Shared RateLimiter (created with defaults if not provided).
            robots_cache: Shared RobotsCache (created if not provided).
            default_timeout: Request timeout in seconds.
            max_redirects: Maximum redirects to follow.
            user_agent: User-Agent header.
            respect_robots: Whether to check robots.txt before fetching.
            max_retries: Maximum retry attempts for transient failures.
            retry_base_delay: Base delay for exponential backoff.
            retry_max_delay: Maximum delay for retries.
        """
        self._owns_client = client is None
        self._client = client or httpx.AsyncClient(
            timeout=default_timeout,
            follow_redirects=True,
            max_redirects=max_redirects,
            headers={"User-Agent": user_agent},
        )
        self._rate_limiter = rate_limiter or RateLimiter()
        self._robots_cache = robots_cache or RobotsCache(self._client)
        self._respect_robots = respect_robots
        self._max_retries = max_retries
        self._retry_base_delay = retry_base_delay
        self._retry_max_delay = retry_max_delay

        # Per-host conditional headers cache (in-memory, no persistence in Phase 2)
        self._conditional_cache: dict[str, _ConditionalHeaders] = {}

        # Create retryer with configurable params
        self._retryer = AsyncRetrying(
            wait=wait_exponential_jitter(initial=retry_base_delay, max=retry_max_delay),
            stop=stop_after_attempt(max_retries),
            retry=retry_if_exception_type(
                (httpx.RequestError, httpx.TimeoutException, httpx.HTTPStatusError),
            ),
            reraise=True,
        )

    async def __aenter__(self) -> AsyncFetcher:
        return self

    async def __aexit__(self, *_) -> None:
        await self.close()

    async def close(self) -> None:
        """Close the underlying HTTP client if owned by this fetcher."""
        if self._owns_client:
            await self._client.aclose()

    def _get_conditional_headers(self, host: str) -> _ConditionalHeaders:
        if host not in self._conditional_cache:
            self._conditional_cache[host] = _ConditionalHeaders()
        return self._conditional_cache[host]

    def _update_conditional_headers(self, host: str, headers: httpx.Headers) -> None:
        cond = self._get_conditional_headers(host)
        cond.etag = headers.get("ETag")
        cond.last_modified = headers.get("Last-Modified")

    def _make_conditional_headers(self, host: str) -> dict[str, str]:
        return self._get_conditional_headers(host).to_headers()

    async def _fetch_with_retry(
        self,
        url: str,
        *,
        headers: dict[str, str] | None = None,
    ) -> httpx.Response:
        """Internal fetch with retry logic."""

        async def _do_fetch() -> httpx.Response:
            resp = await self._client.get(url, headers=headers)
            # Raise on 4xx/5xx to trigger retries, but NOT on 304
            if resp.status_code >= 400:
                resp.raise_for_status()
            return resp

        return await self._retryer(_do_fetch)

    async def fetch(
        self,
        url: str,
        *,
        force_refresh: bool = False,
        headers: dict[str, str] | None = None,
    ) -> FetchResult:
        """Fetch a URL with rate limiting, robots.txt, and conditional GET.

        Args:
            url: The URL to fetch.
            force_refresh: Skip conditional headers (ignore cached ETag/Last-Modified).
            headers: Additional headers to send.

        Returns:
            FetchResult with content, headers, and metadata.

        Raises:
            httpx.HTTPStatusError: On 4xx/5xx responses (after retries).
            PermissionError: If robots.txt disallows the URL.
        """
        parsed = urlparse(url)
        host = parsed.hostname or ""
        if not host:
            raise ValueError(f"Invalid URL (no host): {url}")

        # robots.txt check
        if self._respect_robots:
            allowed = await self._robots_cache.can_fetch(url)
            if not allowed:
                raise PermissionError(f"robots.txt disallows: {url}")

        # Rate limit
        async with self._rate_limiter.acquire(host):
            pass  # acquired

        # Build request headers
        request_headers = dict(headers) if headers else {}
        if not force_refresh:
            cond_headers = self._make_conditional_headers(host)
            request_headers.update(cond_headers)

        # Fetch with retry
        try:
            resp = await self._fetch_with_retry(url, headers=request_headers)
        except httpx.HTTPStatusError as e:
            # Re-raise non-retryable status errors
            if e.response.status_code < 500 and e.response.status_code != 429:
                # Convert to FetchResult for 4xx (except 429)
                return FetchResult(
                    url=url,
                    status=e.response.status_code,
                    content=e.response.content,
                    headers=dict(e.response.headers),
                )
            raise

        # Handle 304 Not Modified
        if resp.status_code == 304:
            # Return cached content indicator
            cached = self._get_conditional_headers(host)
            return FetchResult(
                url=url,
                status=304,
                content=None,
                headers=dict(resp.headers),
                etag=cached.etag,
                last_modified=cached.last_modified,
                from_cache=True,
            )

        # Success: update conditional cache
        self._update_conditional_headers(host, resp.headers)

        return FetchResult(
            url=url,
            status=resp.status_code,
            content=resp.content,
            headers=dict(resp.headers),
            etag=resp.headers.get("ETag"),
            last_modified=resp.headers.get("Last-Modified"),
        )

    async def fetch_all(
        self,
        urls: list[str],
        *,
        max_concurrent: int = 10,
        force_refresh: bool = False,
    ) -> list[FetchResult]:
        """Fetch multiple URLs concurrently with a semaphore limit."""
        semaphore = asyncio.Semaphore(max_concurrent)

        async def _fetch_one(url: str) -> FetchResult:
            async with semaphore:
                return await self.fetch(url, force_refresh=force_refresh)

        return await asyncio.gather(*[_fetch_one(url) for url in urls])

    def clear_conditional_cache(self, host: str | None = None) -> None:
        """Clear conditional headers cache for a host or all hosts."""
        if host:
            self._conditional_cache.pop(host, None)
        else:
            self._conditional_cache.clear()
