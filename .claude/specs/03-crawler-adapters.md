# Spec: Crawler Adapters

## Overview
This is **Phase 2 (part)** of `plan.md §7` — the async crawler layer with jurisdiction-specific source adapters. It implements the `crawler/` package: an `AsyncFetcher` with conditional GET (ETag/Last-Modified 304 handling), per-host rate limiting (token bucket + jitter), `RobotsCache` (cached `robots.txt` parsing with TTL), a `BaseAdapter` abstract class, and four concrete adapters (`RBIAdapter`, `SEBIAdapter`, `FDAAdapter`, `EUAIActAdapter`) that discover entries via HTML listing pagination and/or RSS/Atom/JSON feeds. It also provides `CrawlerAgent` to orchestrate fetch queues, de-duplicate seen URLs within a run, and emit `RawDocument` objects for downstream normalize/persist stages. This module is needed now because Phase 3 (dedup/embeddings/RAG) and Phase 4+ (classification/summarization/risk) cannot run without a stream of normalized raw documents; the crawler is the pipeline's ingestion front door.

## Depends on
- **Phase 0 — Scaffolding (complete).** `pyproject.toml`, `Makefile`, `ruff`/`black`/`mypy` config, empty package skeleton, `.env.example` with `REGMON_DB_URL` declared.
- **Phase 1 — Core data + persistence (spec `02-data-models-persistence`, complete).** Provides `RegulatorySource` config model, `RawDocument` Pydantic model, `Jurisdiction` enum, `SourceRegistry`/`load_sources()` from `config/source_registry.py`, and the async SQLite engine + `DocumentStore`/`AuditLog` for persistence (though the crawler itself only emits `RawDocument`s; persistence is the caller's responsibility).
- `plan.md §7 Phase 2` explicitly scopes `crawler/` + `parser/` + `normalize/`. This spec covers only the **crawler + adapters** subset.

## Data models touched
Consumes / produces models from `plan.md §4.2` (already defined in Phase 1):
- **Consumes:** `RegulatorySource` (from `config.source_registry`), `Jurisdiction` enum — used to configure adapters.
- **Produces:** `RawDocument` — emitted by `CrawlerAgent` for each successfully fetched entry. Fields populated: `source_id`, `url`, `fetched_at` (UTC), `http_status`, `content_bytes`, `headers`, `etag`, `last_modified`.
- **Internal (not persisted here):** `RemoteEntry` (dataclass, listing/feed discovery), `FetchResult` (dataclass, fetch outcome with 304 support), `AdapterContext` (runtime context passed to adapters).

No new Pydantic models or enums introduced by this module.

## Database changes
**No database changes.** This module performs HTTP I/O only. It emits `RawDocument` objects; the caller (pipeline orchestrator, Phase 6) persists them via `DocumentStore.upsert()` introduced in Phase 1. No new tables, columns, or indexes.

## Module contract
- **Inputs:**
  - `SourceRegistry` (iterable of `RegulatorySource`) — drives which adapters to instantiate.
  - Optional `since: datetime | None` — incremental crawl cutoff (only entries newer than this).
  - Optional `max_concurrent_sources`, `max_concurrent_fetches` — concurrency knobs for `CrawlerAgent`.
  - Shared `AsyncFetcher` (or one created with defaults) — provides `httpx.AsyncClient`, `RateLimiter`, `RobotsCache`.
- **Outputs:**
  - Async iterator of `RawDocument` via `CrawlerAgent.crawl()` / `CrawlerAgent.crawl_source()`.
  - Per-source `CrawlerStats` (entries found/fetched/skipped/errors, duration).
- **Key functions/classes (signatures match `plan.md §5.2` style):**
  - `config/source_registry.py` (Phase 1, re-used):
    - `load_sources(path?) -> list[RegulatorySource]`
    - `SourceRegistry` with `get(id)`, `by_adapter(adapter)`, `by_jurisdiction(jurisdiction)`
  - `crawler/fetcher.py`:
    - `class AsyncFetcher`
      - `__init__(client?, rate_limiter?, robots_cache?, default_timeout=30.0, max_redirects=10, user_agent="RegMon/1.0", respect_robots=True, max_retries=3, retry_base_delay=1.0, retry_max_delay=30.0)`
      - `async fetch(url, *, force_refresh=False, headers=None) -> FetchResult`
      - `async fetch_all(urls, *, max_concurrent=10, force_refresh=False) -> list[FetchResult]`
      - `async close()`
      - `clear_conditional_cache(host?)`
  - `crawler/rate_limiter.py`:
    - `class RateLimiter`
      - `__init__(min_interval=1.0, jitter=0.1)` — token-bucket style per-host
      - `async acquire(host: str) -> None`
  - `crawler/robots_cache.py`:
    - `class RobotsCache`
      - `__init__(client, ttl_seconds=3600, failure_ttl=300, user_agent="RegMon/1.0")`
      - `async can_fetch(url) -> bool` (fail-open on errors)
      - `clear(host?)`
  - `crawler/types.py`:
    - `@dataclass RemoteEntry(url, title?, published_date?, summary?, metadata?)`
    - `@dataclass FetchResult(url, status, content, headers, etag?, last_modified?, from_cache=False)` with `is_not_modified`, `is_success`, `content_hash` properties.
  - `crawler/adapters/base.py`:
    - `@dataclass AdapterContext(source, fetcher, base_url, since?, crawl_policy?)`
    - `class BaseAdapter(ABC)`
      - `__init__(context: AdapterContext)`
      - `abstract async list_entries() -> AsyncIterator[RemoteEntry]`
      - `async fetch_entry(entry: RemoteEntry) -> FetchResult` (default uses `fetcher.fetch`)
      - `result_to_raw_document(result: FetchResult, entry: RemoteEntry) -> RawDocument`
      - Helpers: `_parse_date(text)`, `_extract_reference(text)`, `_make_absolute_url(href)`, `_fetch_listing_page(url) -> BeautifulSoup | None`
      - Class vars: `DATE_PATTERNS`, `REF_PATTERN` (override in subclasses)
  - `crawler/adapters/rbi.py`:
    - `class RBIAdapter(BaseAdapter)` — notifications + press releases; paginated HTML table scraping; `crawl_policy: max_pages`
  - `crawler/adapters/sebi.py`:
    - `class SEBIAdapter(BaseAdapter)` — legal circulars; paginated HTML table/card scraping; `crawl_policy: max_pages`
  - `crawler/adapters/fda.py`:
    - `class FDAAdapter(BaseAdapter)` — RSS feed (`feedparser`) + Federal Register JSON API; `crawl_policy: max_items`
  - `crawler/adapters/eu_ai_act.py`:
    - `class EUAIActAdapter(BaseAdapter)` — newsroom paginated HTML article cards; `crawl_policy: max_pages`
  - `crawler/adapters/__init__.py`:
    - `register_adapter(name) -> decorator`
    - `get_adapter_class(name) -> type[BaseAdapter] | None`
    - `create_adapter(source, fetcher, since?) -> BaseAdapter`
  - `crawler/agent.py`:
    - `@dataclass CrawlerStats(source_id, entries_found, entries_fetched, entries_skipped, errors, start_time, end_time?)`
    - `class CrawlerAgent`
      - `__init__(fetcher?, since?, max_concurrent_sources=4, max_concurrent_fetches=10)`
      - `async crawl() -> AsyncIterator[RawDocument]` — all sources
      - `async crawl_source(source_id) -> AsyncIterator[RawDocument]` — single source
      - `async crawl_sources(source_ids) -> AsyncIterator[RawDocument]` — subset
      - `get_stats() -> list[CrawlerStats]`
- **Edge cases (explicit list):**
  - `robots.txt` disallows URL → `PermissionError` raised by `AsyncFetcher.fetch`, caught by `CrawlerAgent`, logged, `stats.errors += 1`, URL skipped.
  - 304 Not Modified → `FetchResult.from_cache=True`, `content=None`, `CrawlerAgent` treats as "skip" (increments `entries_skipped`, does not emit `RawDocument`).
  - 4xx (except 429) / 5xx after retries → `FetchResult` with error status returned; `CrawlerAgent` logs, increments `errors`, does not emit.
  - Network error / timeout after retries → exception propagates; `CrawlerAgent` catches, logs, increments `errors`.
  - Adapter `list_entries` yields no entries → `stats.entries_found=0`, source completes silently.
  - `since` cutoff filters entries at adapter level (adapter checks `published_date < since` and continues).
  - Duplicate URL within a run → `CrawlerAgent` maintains a `seen_urls: set[str]`; second occurrence increments `entries_skipped`, not fetched.
  - Empty `content_bytes` on 200 → still emitted as `RawDocument` (downstream parser handles empty body).
  - Missing `listing_url` and `feed_url` on source → adapter's `list_entries` returns immediately (yields nothing).

## Provider abstraction
**No provider abstraction — deterministic module.** All I/O is standard `httpx` + `feedparser` + `BeautifulSoup` (all OSS, no API keys). The only "backend" choice is the HTTP client, which is injectable via `AsyncFetcher.__init__(client=...)` for testing (`httpx.MockTransport`). No LLM, embedding, or vector-store providers are touched. This aligns with the OSS-only rule: `REGMON_LLM_PROVIDER`/`REGMON_EMBEDDING_PROVIDER` are declared in `Settings` (Phase 1) but **not read** by this module; they are for Phases 3–7.

## Audit & observability
- **No `AuditEvent` emitted by this module.** The crawler is a pre-pipeline ingestion layer; the orchestrator (Phase 6) emits `PipelineStage.CRAWL` events when it wraps the crawler. `CrawlerAgent` returns `CrawlerStats` for the caller to include in `RunContext.counts` and `RunContext.errors`.
- **Logging:** `CrawlerAgent` uses `logging.getLogger(__name__)` at INFO for per-source start/complete, WARNING for fetch errors, DEBUG for per-URL fetch/skip. No structured log fields mandated.

## Files to change
- `pyproject.toml` — add **core runtime deps**: `httpx>=0.27`, `beautifulsoup4>=4.12`, `feedparser>=6.0`, `tenacity>=8.2`, `lxml>=5.0` (parser backend for BS4). Already present in main; verify.
- `.env.example` — no new vars (crawler reads nothing from env beyond what `Settings` already has).
- `src/regmon/crawler/__init__.py` — re-export public API: `AsyncFetcher`, `RateLimiter`, `RobotsCache`, `RemoteEntry`, `FetchResult`, `BaseAdapter`, `create_adapter`, `CrawlerAgent`, `CrawlerStats`.
- `src/regmon/config/source_registry.py` — already exists (Phase 1), no changes needed.

## Files to create
All exist in main; this spec documents them as the canonical Phase 2 crawler deliverables:
- `src/regmon/crawler/types.py` — `RemoteEntry`, `FetchResult`
- `src/regmon/crawler/fetcher.py` — `AsyncFetcher`
- `src/regmon/crawler/rate_limiter.py` — `RateLimiter`
- `src/regmon/crawler/robots_cache.py` — `RobotsCache`
- `src/regmon/crawler/adapters/base.py` — `AdapterContext`, `BaseAdapter`
- `src/regmon/crawler/adapters/rbi.py` — `RBIAdapter`
- `src/regmon/crawler/adapters/sebi.py` — `SEBIAdapter`
- `src/regmon/crawler/adapters/fda.py` — `FDAAdapter`
- `src/regmon/crawler/adapters/eu_ai_act.py` — `EUAIActAdapter`
- `src/regmon/crawler/adapters/__init__.py` — registry + `create_adapter`
- `src/regmon/crawler/agent.py` — `CrawlerAgent`, `CrawlerStats`
- `tests/fixtures/rbi/` — recorded HTML for notifications listing, notification detail, press listing, press detail
- `tests/fixtures/sebi/` — recorded HTML for circulars listing + detail
- `tests/fixtures/fda/` — recorded RSS XML + Federal Register JSON
- `tests/fixtures/eu_ai_act/` — recorded HTML for newsroom listing + article detail
- `tests/conftest.py` — add `mock_fetcher` fixture (shared `httpx.AsyncClient` with `MockTransport` returning fixtures)
- `tests/test_crawler_fetcher.py` — `AsyncFetcher` unit tests (conditional GET, 304, retry, rate limit, robots)
- `tests/test_crawler_adapters.py` — each adapter's `list_entries` against fixtures; `fetch_entry` returns expected `FetchResult`
- `tests/test_crawler_agent.py` — `CrawlerAgent` orchestrates multiple sources, de-dups URLs, emits `RawDocument`, collects stats

## New dependencies
- **Core runtime (added to `[project] dependencies` in `pyproject.toml`):** `httpx>=0.27`, `beautifulsoup4>=4.12`, `feedparser>=6.0`, `tenacity>=8.2`, `lxml>=5.0`
- **No new optional extras.** All deps are OSS and required for the crawler to function (not behind an extra).
- **Dev deps unchanged** (pytest/pytest-asyncio/pytest-cov/httpx already present from Phase 0/1).

## Rules for implementation
- **Fully async** — all I/O methods `async def`; `AsyncFetcher` uses `httpx.AsyncClient`; adapters `await` fetcher; `CrawlerAgent` uses `asyncio.gather`/`Semaphore` for concurrency.
- **Provider protocol only for test injection** — `AsyncFetcher` accepts `client: httpx.AsyncClient | None`; tests pass a client with `httpx.MockTransport` returning recorded fixtures. No other abstraction layer.
- **No secrets/config outside `config/Settings`** — crawler reads nothing from `os.environ`; `Settings` (Phase 1) is not used directly here (crawler is config-driven via `RegulatorySource` objects).
- **All DB writes through `src/regmon/db/`** — this module does **zero** DB writes; it emits `RawDocument` for the orchestrator to persist.
- **Audit log append-only** — not applicable here (no `AuditEvent` emission); Phase 6 orchestrator owns that.
- **Deterministic under `mock`** — tests use `httpx.MockTransport` with recorded fixtures; no real network calls in `make test`. `feedparser` is deterministic on fixed XML.
- **Type-hinted, passes `mypy` and `ruff`** — strict signatures on all public classes; `ignored_missing_imports` for optional deps in `mypy` config (already set for `lxml`, `feedparser`, `httpx`, `tenacity`, `bs4`).
- **Respects `REGMON_DRY_RUN`** — not applicable (no outbound side effects beyond HTTP GET); orchestrator may gate the crawler itself.

## Testing plan
- **Unit tests (no `@pytest.mark.integration`):**
  - `test_crawler_fetcher.py`:
    - `AsyncFetcher.fetch` with `MockTransport`: 200 returns content, updates ETag/Last-Modified cache.
    - 304 returns `FetchResult(from_cache=True, content=None)` without calling network again.
    - 404/500 returns `FetchResult` with status, no exception (except 429/5xx retry).
    - Retry with exponential backoff on `httpx.RequestError` / timeout / 5xx / 429 (use `tenacity` retry policy verification via mock call count).
    - `RateLimiter.acquire` enforces min interval per host (time-mocked or async sleep assertion).
    - `RobotsCache.can_fetch`: allowed → True; disallowed → False; fetch error → True (fail-open) with short TTL.
    - `fetch_all` respects `max_concurrent` semaphore.
  - `test_crawler_adapters.py` (one per adapter, parameterized):
    - `RBIAdapter.list_entries` on recorded notification listing HTML → yields `RemoteEntry` with correct `url`, `title`, `published_date`, `metadata["reference_number"]`, `metadata["document_type"]`.
    - `RBIAdapter.list_entries` on press releases listing → yields entries with `document_type="PRESS_RELEASE"`.
    - `SEBIAdapter.list_entries` on circulars listing → yields entries with `document_type="CIRCULAR"`.
    - `FDAAdapter.list_entries` on RSS fixture → yields entries with `summary`, `metadata["feed_id"]`.
    - `FDAAdapter.list_entries` on Federal Register JSON fixture → yields entries with `metadata["fr_citation"]`, `metadata["agencies"]`.
    - `EUAIActAdapter.list_entries` on newsroom listing → yields entries with `summary`, `metadata["reference_number"]` (Article/Annex/Recital).
    - Each adapter's `fetch_entry` on recorded detail page → `FetchResult` with 200, non-empty content.
    - `since` cutoff filters out older entries (mock `datetime` in fixture).
    - `crawl_policy.max_pages` / `max_items` limits respected.
  - `test_crawler_agent.py`:
    - `CrawlerAgent.crawl()` iterates all sources from `SourceRegistry`, emits `RawDocument` for each fetched entry.
    - Duplicate URL across sources → second occurrence skipped, `stats.entries_skipped += 1`.
    - `since` parameter passed to adapters → older entries not fetched.
    - Errors in one source don't stop others; `stats.errors` aggregated per source.
    - `get_stats()` returns `CrawlerStats` with correct counts and duration.
- **Fixtures under `tests/fixtures/<jurisdiction>/`:**
  - `rbi/notifications_list_page1.html`, `rbi/notification_detail.html`, `rbi/press_list_page1.html`, `rbi/press_detail.html`
  - `sebi/circulars_list_page1.html`, `sebi/circular_detail.html`
  - `fda/press_releases_rss.xml`, `fda/federal_register.json`
  - `eu_ai_act/newsroom_page1.html`, `eu_ai_act/article_detail.html`
  - (Fixtures are recorded HTML/XML/JSON; `conftest.py` provides `mock_fetcher` fixture mapping URLs to file contents.)
- **Integration test:** Not in this spec (Phase 2 exit says "offline tests with `httpx.MockTransport`"; full pipeline integration with parser/normalize is Phase 2 end-to-end but not a separate `@pytest.mark.integration` here).

## Definition of done
- [ ] `pip install -e ".[dev]"` succeeds; new deps (`httpx`, `beautifulsoup4`, `feedparser`, `tenacity`, `lxml`) installed.
- [ ] `make lint` passes (ruff + black `--check` + mypy) on new `crawler/` code.
- [ ] `make test` passes — all new unit tests green, existing Phase 0/1 tests still green.
- [ ] **Phase-2a exit gate (crawler + adapters):** a test runs `CrawlerAgent.crawl()` over fixtures for all 4 jurisdictions and asserts:
    - At least one `RawDocument` emitted per source (6 sources total per `sources.yaml`).
    - Each `RawDocument` has non-empty `content_bytes`, valid `http_status` (200), `source_id` matching a configured source.
    - `CrawlerStats` for each source shows `entries_found > 0`, `entries_fetched > 0`, `errors == 0`.
    - No real HTTP calls made (verify via `httpx.MockTransport` call count or monkeypatched `httpx.AsyncClient`).
- [ ] Fixtures committed under `tests/fixtures/<jurisdiction>/` (recorded once; no network in CI).
- [ ] `conftest.py` provides reusable `mock_fetcher` fixture for adapter tests.
- [ ] `src/regmon/crawler/__init__.py` re-exports full public API so `from regmon.crawler import CrawlerAgent, AsyncFetcher, create_adapter, RemoteEntry, FetchResult, BaseAdapter` works.
- [ ] No edits to `cli.py`, `scheduler.py`, `pipeline/`, `parser/`, `normalize/`, `models/`, `db/`, `config/` (except `__init__.py` re-exports if needed) — surgical.
- [ ] `REGMON_DRY_RUN` not read (no outbound effects); OSS-only deps confirmed (no `openai` import, no paid API calls).

---

**Branch:** `feature/crawler-adapters` (already exists in main; this spec documents the as-implemented state for Plan Mode sign-off)
**Spec file:** `.claude/specs/03-crawler-adapters.md`
**Title:** Crawler Adapters
