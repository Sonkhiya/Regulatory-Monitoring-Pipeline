"""Crawler module — async fetch, rate limiting, robots.txt, adapters (plan.md §5.2)."""

from regmon.crawler.adapters import (
    AdapterContext,
    BaseAdapter,
    create_adapter,
    get_adapter_class,
    register_adapter,
)
from regmon.crawler.agent import CrawlerAgent, CrawlerStats
from regmon.crawler.fetcher import AsyncFetcher, FetchResult
from regmon.crawler.rate_limiter import AsyncRateLimiter, RateLimiter
from regmon.crawler.robots_cache import RobotsCache
from regmon.crawler.types import FetchResult as FetchResultType
from regmon.crawler.types import RemoteEntry

__all__ = [
    "AdapterContext",
    "AsyncFetcher",
    "AsyncRateLimiter",
    "BaseAdapter",
    "CrawlerAgent",
    "CrawlerStats",
    "FetchResult",
    "FetchResultType",
    "RateLimiter",
    "RemoteEntry",
    "RobotsCache",
    "create_adapter",
    "get_adapter_class",
    "register_adapter",
]
