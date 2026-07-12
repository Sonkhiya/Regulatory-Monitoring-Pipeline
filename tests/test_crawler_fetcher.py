"""Unit tests for AsyncFetcher, RateLimiter, and RobotsCache (Phase 2 Crawler)."""

from __future__ import annotations

import asyncio
import time

import httpx
import pytest

from regmon.crawler.fetcher import AsyncFetcher
from regmon.crawler.rate_limiter import RateLimiter
from regmon.crawler.robots_cache import RobotsCache


class TestAsyncFetcher:
    """Tests for AsyncFetcher with MockTransport fixtures."""

    @pytest.mark.asyncio
    async def test_fetch_200_returns_content_and_caches_etag(
        self, mock_transport: httpx.MockTransport
    ):
        """Fetch 200 OK returns content and updates ETag/Last-Modified cache."""
        fetcher = AsyncFetcher(client=httpx.AsyncClient(transport=mock_transport))

        result = await fetcher.fetch("https://www.rbi.org.in/Scripts/NotificationUser.aspx")

        assert result.status == 200
        assert result.content is not None
        assert len(result.content) > 0
        assert result.is_success
        assert not result.from_cache

        # Second fetch should include conditional headers
        _ = await fetcher.fetch("https://www.rbi.org.in/Scripts/NotificationUser.aspx")
        # The mock always returns 200, but in reality it would be 304
        # We verify the cache was updated
        assert fetcher._get_conditional_headers("www.rbi.org.in").etag is not None

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_304_returns_cached_result(self):
        """Fetch returning 304 Not Modified returns cached indicator."""
        # Create a fetcher with a handler that returns 304 on conditional requests
        call_count = 0

        async def handler(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            # Return 304 if conditional headers are present
            if request.headers.get("If-None-Match") or request.headers.get("If-Modified-Since"):
                return httpx.Response(304, headers={"ETag": "abc123"})
            # First request: return 200 with ETag
            return httpx.Response(200, content=b"content", headers={"ETag": "abc123"})

        fetcher = AsyncFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler)))

        # First fetch - should return 200 and populate cache
        result1 = await fetcher.fetch("https://example.com/test")
        assert result1.status == 200
        assert result1.content == b"content"

        # Second fetch - should include conditional headers and get 304
        result2 = await fetcher.fetch("https://example.com/test")

        assert result2.status == 304
        assert result2.from_cache
        assert result2.is_not_modified
        assert result2.content is None

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_404_returns_result_no_exception(self, mock_transport: httpx.MockTransport):
        """404 returns FetchResult with status, doesn't raise."""

        # Create client that returns 404 for unknown URLs
        async def handler_404(request: httpx.Request) -> httpx.Response:
            if "unknown" in str(request.url):
                return httpx.Response(404, content=b"Not Found")
            return httpx.Response(200, content=b"OK")

        fetcher = AsyncFetcher(client=httpx.AsyncClient(transport=httpx.MockTransport(handler_404)))

        result = await fetcher.fetch("https://www.rbi.org.in/unknown")

        assert result.status == 404
        assert not result.is_success
        # No exception raised

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_retry_on_5xx_then_succeeds(self):
        """Retry with exponential backoff on 5xx, then succeeds on 200."""
        call_count = 0

        async def handler_retry(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 3:
                return httpx.Response(500, content=b"Server Error")
            return httpx.Response(200, content=b"Success")

        fetcher = AsyncFetcher(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler_retry)),
            max_retries=3,
            retry_base_delay=0.01,
            retry_max_delay=0.1,
        )

        result = await fetcher.fetch("https://example.com/test")

        assert result.status == 200
        assert call_count == 3  # Initial + 2 retries

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_retry_on_429_then_succeeds(self):
        """Retry on 429 Too Many Requests."""
        call_count = 0

        async def handler_429(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if call_count < 2:
                return httpx.Response(429, content=b"Rate Limited")
            return httpx.Response(200, content=b"OK")

        fetcher = AsyncFetcher(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler_429)),
            max_retries=3,
            retry_base_delay=0.01,
            retry_max_delay=0.1,
        )

        result = await fetcher.fetch("https://example.com/test")

        assert result.status == 200
        assert call_count == 2

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_fetch_all_respects_max_concurrent(self):
        """fetch_all limits concurrent requests via semaphore."""
        active = 0
        max_active = 0

        async def handler_slow(request: httpx.Request) -> httpx.Response:
            nonlocal active, max_active
            active += 1
            max_active = max(max_active, active)
            await asyncio.sleep(0.05)
            active -= 1
            return httpx.Response(200, content=f"Response {request.url}".encode())

        fetcher = AsyncFetcher(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler_slow)),
        )

        urls = [f"https://example.com/{i}" for i in range(20)]
        results = await fetcher.fetch_all(urls, max_concurrent=5)

        assert len(results) == 20
        assert max_active <= 5  # Never more than 5 concurrent

        await fetcher.close()

    @pytest.mark.asyncio
    async def test_robots_txt_disallowed_raises(self, mock_transport: httpx.MockTransport):
        """Fetch respects robots.txt and raises PermissionError when disallowed."""

        # Build mock that returns disallow for specific path
        async def handler_robots(request: httpx.Request) -> httpx.Response:
            if "/robots.txt" in str(request.url):
                return httpx.Response(200, content=b"User-agent: *\nDisallow: /private/")
            if "/private/" in str(request.url):
                return httpx.Response(200, content=b"Private content")
            return httpx.Response(200, content=b"Public content")

        fetcher = AsyncFetcher(
            client=httpx.AsyncClient(transport=httpx.MockTransport(handler_robots)),
            respect_robots=True,
        )

        # Public path should work
        result = await fetcher.fetch("https://example.com/public/page")
        assert result.is_success

        # Private path should raise PermissionError
        with pytest.raises(PermissionError):
            await fetcher.fetch("https://example.com/private/page")

        await fetcher.close()


class TestRateLimiter:
    """Tests for RateLimiter per-host token bucket."""

    @pytest.mark.asyncio
    async def test_acquire_enforces_min_interval(self):
        """acquire() enforces minimum interval between requests to same host."""
        limiter = RateLimiter(rate_per_minute=60, burst=1, jitter=0.0)  # 1 per second, no burst

        start = time.monotonic()
        async with limiter.acquire("example.com"):
            pass
        async with limiter.acquire("example.com"):
            pass
        elapsed = time.monotonic() - start

        # Two acquires at 1/sec should take ~1 second
        assert elapsed >= 0.9  # Allow small margin

    @pytest.mark.asyncio
    async def test_different_hosts_independent(self):
        """Different hosts have independent rate limits."""
        limiter = RateLimiter(rate_per_minute=60, burst=1, jitter=0.0)

        start = time.monotonic()
        async with limiter.acquire("host1.com"):
            pass
        async with limiter.acquire("host2.com"):
            pass
        elapsed = time.monotonic() - start

        # Should be near-instant since different hosts
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_burst_allows_initial_burst(self):
        """burst parameter allows initial burst of requests."""
        limiter = RateLimiter(rate_per_minute=60, burst=5, jitter=0.0)  # 1/sec, burst 5

        start = time.monotonic()
        for _ in range(5):
            async with limiter.acquire("example.com"):
                pass
        elapsed = time.monotonic() - start

        # First 5 should be instant (burst)
        assert elapsed < 0.1

    @pytest.mark.asyncio
    async def test_timeout_raises(self):
        """acquire() raises TimeoutError when timeout expires."""
        limiter = RateLimiter(rate_per_minute=60, burst=1, jitter=0.0)

        # Fill the bucket
        async with limiter.acquire("example.com"):
            pass

        # Next acquire should wait ~1s, but we give 0.05s timeout
        with pytest.raises(asyncio.TimeoutError):
            async with limiter.acquire("example.com", timeout=0.05):
                pass


class TestRobotsCache:
    """Tests for RobotsCache with TTL and fail-open behavior."""

    @pytest.mark.asyncio
    async def test_can_fetch_allowed(self, mock_transport: httpx.MockTransport):
        """can_fetch returns True for allowed paths."""

        # Mock robots.txt allowing all
        async def handler_allow(request: httpx.Request) -> httpx.Response:
            if "/robots.txt" in str(request.url):
                return httpx.Response(200, content=b"User-agent: *\nAllow: /")
            return httpx.Response(200, content=b"OK")

        cache = RobotsCache(httpx.AsyncClient(transport=httpx.MockTransport(handler_allow)))

        allowed = await cache.can_fetch("https://example.com/page")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_can_fetch_disallowed(self):
        """can_fetch returns False for disallowed paths."""

        async def handler_disallow(request: httpx.Request) -> httpx.Response:
            if "/robots.txt" in str(request.url):
                return httpx.Response(200, content=b"User-agent: *\nDisallow: /private/")
            return httpx.Response(200, content=b"OK")

        cache = RobotsCache(httpx.AsyncClient(transport=httpx.MockTransport(handler_disallow)))

        allowed = await cache.can_fetch("https://example.com/private/page")
        assert allowed is False

    @pytest.mark.asyncio
    async def test_can_fetch_fail_open_on_error(self):
        """can_fetch returns True (fail-open) on fetch error."""

        async def handler_error(request: httpx.Request) -> httpx.Response:
            if "/robots.txt" in str(request.url):
                return httpx.Response(500, content=b"Error")
            return httpx.Response(200, content=b"OK")

        cache = RobotsCache(httpx.AsyncClient(transport=httpx.MockTransport(handler_error)))

        # Should fail-open and return True
        allowed = await cache.can_fetch("https://example.com/page")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_can_fetch_fail_open_on_network_error(self):
        """can_fetch returns True (fail-open) on network error."""

        async def handler_network_error(request: httpx.Request) -> httpx.Response:
            raise httpx.RequestError("Connection failed")

        cache = RobotsCache(httpx.AsyncClient(transport=httpx.MockTransport(handler_network_error)))

        allowed = await cache.can_fetch("https://example.com/page")
        assert allowed is True

    @pytest.mark.asyncio
    async def test_cache_ttl_respected(self):
        """Cached robots.txt is reused within TTL."""
        call_count = 0

        async def handler_counter(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            if "/robots.txt" in str(request.url):
                call_count += 1
                return httpx.Response(200, content=b"User-agent: *\nAllow: /")
            return httpx.Response(200, content=b"OK")

        cache = RobotsCache(
            httpx.AsyncClient(transport=httpx.MockTransport(handler_counter)),
            ttl_seconds=3600,
        )

        # First call fetches robots.txt
        await cache.can_fetch("https://example.com/page1")
        assert call_count == 1

        # Second call uses cache
        await cache.can_fetch("https://example.com/page2")
        assert call_count == 1  # Still 1

    @pytest.mark.asyncio
    async def test_failure_ttl_shorter(self):
        """Failed fetch cached with shorter failure TTL."""
        call_count = 0

        async def handler_fail_then_succeed(request: httpx.Request) -> httpx.Response:
            nonlocal call_count
            call_count += 1
            if "/robots.txt" in str(request.url):
                if call_count == 1:
                    return httpx.Response(500, content=b"Error")
                return httpx.Response(200, content=b"User-agent: *\nAllow: /")
            return httpx.Response(200, content=b"OK")

        cache = RobotsCache(
            httpx.AsyncClient(transport=httpx.MockTransport(handler_fail_then_succeed)),
            ttl_seconds=3600,
            failure_ttl=0.1,  # Very short failure TTL
        )

        # First call fails, caches fail-open
        await cache.can_fetch("https://example.com/page1")
        assert call_count == 1

        # Wait for failure TTL to expire
        await asyncio.sleep(0.2)

        # Next call should re-fetch
        await cache.can_fetch("https://example.com/page2")
        assert call_count == 2
