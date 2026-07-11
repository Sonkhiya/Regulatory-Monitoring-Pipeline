"""Adapter factory for creating jurisdiction-specific crawlers."""

from __future__ import annotations

from datetime import datetime
from typing import TYPE_CHECKING

from regmon.config.source_registry import RegulatorySource
from regmon.crawler.adapters.base import AdapterContext, BaseAdapter
from regmon.crawler.fetcher import AsyncFetcher

if TYPE_CHECKING:
    from regmon.crawler.fetcher import AsyncFetcher


_ADAPTER_MAP: dict[str, type[BaseAdapter]] = {}


def register_adapter(name: str):
    """Decorator to register an adapters class by name."""

    def decorator(cls: type[BaseAdapter]) -> type[BaseAdapter]:
        _ADAPTER_MAP[name.lower()] = cls
        return cls

    return decorator


def get_adapter_class(adapter_name: str) -> type[BaseAdapter] | None:
    """Get adapter class by name (case-insensitive)."""
    return _ADAPTER_MAP.get(adapter_name.lower())


def create_adapter(
    source: RegulatorySource,
    fetcher: AsyncFetcher,
    since: datetime | None = None,
) -> BaseAdapter:
    """Create an adapter instance for a source.

    Args:
        source: RegulatorySource configuration.
        fetcher: Shared AsyncFetcher instance.
        since: Optional cutoff datetime for incremental crawling.

    Returns:
        Configured adapter instance.

    Raises:
        ValueError: If adapter name is unknown.
    """
    adapter_cls = get_adapter_class(source.adapter)
    if not adapter_cls:
        available = ", ".join(sorted(_ADAPTER_MAP.keys()))
        raise ValueError(f"Unknown adapter: {source.adapter}. Available: {available}")

    # Determine base URL from listing/feed URL
    from urllib.parse import urlparse

    parsed = urlparse(source.listing_url or source.feed_url or "")
    base_url = f"{parsed.scheme}://{parsed.netloc}"

    context = AdapterContext(
        source=source,
        fetcher=fetcher,
        base_url=base_url,
        since=since,
        crawl_policy=source.crawl_policy or {},
    )

    return adapter_cls(context)


# Import and register all adapters
from regmon.crawler.adapters.eu_ai_act import EUAIActAdapter  # noqa: E402
from regmon.crawler.adapters.fda import FDAAdapter  # noqa: E402
from regmon.crawler.adapters.rbi import RBIAdapter  # noqa: E402
from regmon.crawler.adapters.sebi import SEBIAdapter  # noqa: E402

register_adapter("rbi")(RBIAdapter)
register_adapter("sebi")(SEBIAdapter)
register_adapter("fda")(FDAAdapter)
register_adapter("eu_ai_act")(EUAIActAdapter)

__all__ = [
    "AdapterContext",
    "BaseAdapter",
    "create_adapter",
    "get_adapter_class",
    "register_adapter",
]
