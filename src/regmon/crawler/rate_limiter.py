"""Per-host token-bucket rate limiter with jitter (plan.md §5.2)."""

from __future__ import annotations

import asyncio
import random
import time
from collections import defaultdict
from contextlib import asynccontextmanager
from dataclasses import dataclass, field


@dataclass(slots=True)
class _Bucket:
    """Token bucket state for a single host."""

    tokens: float
    last_refill: float = field(default_factory=time.monotonic)


class RateLimiter:
    """Token-bucket rate limiter with per-host buckets and jitter.

    Each host gets its own bucket. Tokens refill at ``rate_per_minute / 60``
    per second. ``acquire()`` blocks until a token is available (or timeout).

    Args:
        rate_per_minute: Steady-state requests per minute per host.
        burst: Maximum burst allowance (bucket capacity).
        jitter: Fraction of interval to randomly add/subtract (0-1).
    """

    def __init__(
        self,
        rate_per_minute: float = 30,
        burst: int = 5,
        jitter: float = 0.1,
    ) -> None:
        if rate_per_minute <= 0:
            raise ValueError("rate_per_minute must be positive")
        if burst <= 0:
            raise ValueError("burst must be positive")
        if not 0 <= jitter < 1:
            raise ValueError("jitter must be in [0, 1)")

        self._rate_per_second = rate_per_minute / 60.0
        self._burst = burst
        self._jitter = jitter
        self._buckets: dict[str, _Bucket] = defaultdict(lambda: _Bucket(tokens=float(burst)))
        self._lock = asyncio.Lock()

    def _refill(self, bucket: _Bucket, now: float) -> None:
        elapsed = now - bucket.last_refill
        if elapsed > 0:
            bucket.tokens = min(self._burst, bucket.tokens + elapsed * self._rate_per_second)
            bucket.last_refill = now

    @asynccontextmanager
    async def acquire(self, host: str, timeout: float | None = None):
        """Acquire a token for ``host``.

        Yields when a token is available. The token is consumed on entry.
        Raises ``asyncio.TimeoutError`` if ``timeout`` expires.
        """
        deadline = time.monotonic() + timeout if timeout else None

        async with self._lock:
            bucket = self._buckets[host]

        while True:
            now = time.monotonic()
            async with self._lock:
                self._refill(bucket, now)
                if bucket.tokens >= 1:
                    bucket.tokens -= 1
                    break

            # Wait for next token with jitter
            wait = 1.0 / self._rate_per_second
            jitter_amt = wait * self._jitter * random.uniform(-1, 1)
            wait = max(0.01, wait + jitter_amt)

            if deadline:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise asyncio.TimeoutError(f"Rate limiter timeout for {host}")
                wait = min(wait, remaining)

            await asyncio.sleep(wait)

        yield


class AsyncRateLimiter:
    """Async context manager variant for ``async with`` convenience.

    Usage:
        limiter = AsyncRateLimiter(rate_per_minute=30)
        async with limiter("example.com"):
            await fetch(url)
    """

    def __init__(self, rate_per_minute: float = 30, burst: int = 5, jitter: float = 0.1):
        self._limiter = RateLimiter(rate_per_minute, burst, jitter)

    @asynccontextmanager
    async def limit(self, host: str, timeout: float | None = None):
        async with self._limiter.acquire(host, timeout):
            yield
