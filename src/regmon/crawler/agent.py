"""Crawler agent — orchestrates fetch queue, dedup, emits RawDocuments (plan.md §5.2)."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import AsyncIterator
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TYPE_CHECKING

from regmon.config.source_registry import RegulatorySource, get_source_registry
from regmon.crawler.adapters import create_adapter
from regmon.crawler.fetcher import AsyncFetcher
from regmon.crawler.types import RemoteEntry
from regmon.models import RawDocument

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


@dataclass(slots=True)
class CrawlerStats:
    """Per-source crawl statistics."""

    source_id: str
    entries_found: int = 0
    entries_fetched: int = 0
    entries_skipped: int = 0
    errors: int = 0
    start_time: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    end_time: datetime | None = None

    @property
    def duration_seconds(self) -> float:
        end = self.end_time or datetime.now(timezone.utc)
        return (end - self.start_time).total_seconds()


class CrawlerAgent:
    """Orchestrates crawling across all configured sources.

    - Creates adapters for each source
    - Manages seen-URLs dedup within a run
    - Emits RawDocument objects for downstream pipeline
    - Collects per-source stats
    """

    def __init__(
        self,
        fetcher: AsyncFetcher | None = None,
        since: datetime | None = None,
        max_concurrent_sources: int = 4,
        max_concurrent_fetches: int = 10,
    ) -> None:
        """
        Args:
            fetcher: Shared AsyncFetcher (created if not provided).
            since: Only fetch entries published after this datetime.
            max_concurrent_sources: Max sources to crawl in parallel.
            max_concurrent_fetches: Max concurrent fetches per source.
        """
        self._fetcher = fetcher
        self._since = since
        self._max_concurrent_sources = max_concurrent_sources
        self._max_concurrent_fetches = max_concurrent_fetches
        self._source_registry = get_source_registry()
        self._owns_fetcher = fetcher is None

    async def __aenter__(self) -> CrawlerAgent:
        if self._fetcher is None:
            self._fetcher = AsyncFetcher()
        return self

    async def __aexit__(self, *_) -> None:
        if self._owns_fetcher and self._fetcher:
            await self._fetcher.close()

    async def crawl_all(
        self,
        source_ids: list[str] | None = None,
        adapter_names: list[str] | None = None,
    ) -> AsyncIterator[tuple[RawDocument | None, CrawlerStats]]:
        """Crawl all (or selected) sources, yielding RawDocuments with stats.

        Args:
            source_ids: If provided, only crawl these source IDs.
            adapter_names: If provided, only crawl sources using these adapters.

        Yields:
            Tuples of (RawDocument, CrawlerStats) for each fetched document.
            The stats object is updated per-source and same object is yielded
            repeatedly; check at end of each source for final counts.
        """
        sources = list(self._source_registry)

        # Filter sources
        if source_ids:
            sources = [s for s in sources if s.id in source_ids]
        if adapter_names:
            sources = [s for s in sources if s.adapter in adapter_names]

        # Semaphore for concurrent source crawling
        source_semaphore = asyncio.Semaphore(self._max_concurrent_sources)

        async def crawl_one(
            source: RegulatorySource,
        ) -> list[tuple[RawDocument | None, CrawlerStats]]:
            async with source_semaphore:
                results: list[tuple[RawDocument | None, CrawlerStats]] = []
                async for item in self._crawl_source(source):
                    results.append(item)
                return results

        # Run all sources concurrently
        tasks = [crawl_one(s) for s in sources]
        for coro in asyncio.as_completed(tasks):
            results = await coro
            for item in results:
                yield item

    async def _crawl_source(
        self, source: RegulatorySource
    ) -> AsyncIterator[tuple[RawDocument | None, CrawlerStats]]:
        """Crawl a single source end-to-end."""
        stats = CrawlerStats(source_id=source.id)
        logger.info("Starting crawl for source: %s (%s)", source.name, source.id)

        fetcher = self._fetcher
        if fetcher is None:
            fetcher = AsyncFetcher()
        adapter = create_adapter(source, fetcher, since=self._since)

        # Track seen URLs within this run
        seen_urls: set[str] = set()

        try:
            # Collect entries from adapter
            entries: list[RemoteEntry] = []
            async for entry in adapter.list_entries():
                if entry.url in seen_urls:
                    stats.entries_skipped += 1
                    continue
                seen_urls.add(entry.url)
                entries.append(entry)
                stats.entries_found += 1

            logger.info("Source %s: found %d unique entries", source.id, len(entries))

            # Fetch entries with concurrency control
            semaphore = asyncio.Semaphore(self._max_concurrent_fetches)

            async def fetch_one(entry: RemoteEntry) -> RawDocument | None:
                async with semaphore:
                    try:
                        result = await adapter.fetch_entry(entry)
                        if result.is_success:
                            stats.entries_fetched += 1
                            return adapter.result_to_raw_document(result, entry)
                        elif result.is_not_modified:
                            stats.entries_skipped += 1
                            return None
                        else:
                            stats.errors += 1
                            logger.warning("Fetch failed for %s: HTTP %d", entry.url, result.status)
                            return None
                    except Exception as e:
                        stats.errors += 1
                        logger.exception("Error fetching %s: %s", entry.url, e)
                        return None

            # Execute fetches
            fetch_tasks = [fetch_one(e) for e in entries]
            for coro in asyncio.as_completed(fetch_tasks):
                doc = await coro
                if doc:
                    yield doc, stats

        except Exception as e:
            logger.exception("Crawl failed for source %s: %s", source.id, e)
            stats.errors += 1
        finally:
            stats.end_time = datetime.now(timezone.utc)
            logger.info(
                "Finished crawl for %s: found=%d fetched=%d skipped=%d errors=%d (%.1fs)",
                source.id,
                stats.entries_found,
                stats.entries_fetched,
                stats.entries_skipped,
                stats.errors,
                stats.duration_seconds,
            )
            # Yield final stats for this source
            yield None, stats

    async def crawl_source(self, source_id: str) -> AsyncIterator[RawDocument]:
        """Crawl a single source by ID, yielding only RawDocuments."""
        source = self._source_registry.get(source_id)
        if not source:
            raise ValueError(f"Unknown source: {source_id}")

        async for doc, _ in self._crawl_source(source):
            if doc:
                yield doc
