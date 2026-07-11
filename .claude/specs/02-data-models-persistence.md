# Spec: Data Models and Persistence

## Overview
This is **Phase 1** of plan.md §7 — the foundation data layer. It implements `src/regmon/models/` (every enum and Pydantic domain model from plan.md §4.1/§4.2) and `src/regmon/db/` (SQLAlchemy async engine factory, init schema, a `DocumentRecord` document store, and an append-only `AuditEvent` audit log per plan.md §5.16). It implements the **NORMALIZE→DEDUP-adjacent persistence** footprint: specifically it gives Phase 2+ a place to persist canonical documents and to record auditable events — the two cross-cutting stores every later stage writes to (plan.md §2 "Cross-cutting: SQLite/Postgres DB"). It also stands up the minimal `config/Settings` that the db layer reads its connection string from, so that no secret/config value is read outside `config/Settings`. It touches no pipeline stage's runtime behavior; it provides the typed vocabulary and persistence substrate the pipeline stages will populate in Phases 2–6. It is needed now because Phase 2 (crawler/parser/normalize) cannot emit a `NormalizedDocument`→`DocumentRecord` without these models and a working async store, and Phase 3+ cannot audit without the log.

## Depends on
- **Phase 0 — Scaffolding (complete).** Committed at `314c333`, merged to `main`. Provides the importable `src/regmon` package, `pyproject.toml` (with `dev`/`faiss`/`chroma`/`local-llm`/`local-embeddings` extras), `Makefile` (`make lint`/`make test` green on the empty skeleton), `.env.example` (with `REGMON_DB_URL` declared but unwired), the empty `models/`/`db/`/`config/` stub packages, the `llm/` shared-provider seam, the pytest `integration` marker, and the working ruff/black/mypy toolchain. See `.claude/specs/01-project-scaffolding.md`.
- plan.md §7 Phase 1 explicitly scopes `models/` + `db/` (+ migrations/init schema).
- No other module phases are required.

## Data models touched
Implements **all** of plan.md §4.1 enums and §4.2 core Pydantic models (Phase 1 is the single home for the typed vocabulary):

- **Enums (plan.md §4.1):** `Jurisdiction`, `DocumentType`, `Urgency`, `RiskLevel`, `PipelineStage`, `ApprovalDecision`, `RunStatus`.
- **Pydantic models (plan.md §4.2):**
  - `RegulatorySource`, `RawDocument`, `ParsedDocument`, `NormalizedDocument`, `DocumentRecord`
  - `ClassificationResult`, `SummaryResult`, `RiskAssessment`, `ActionItem`, `ActionPlan`
  - `ApprovalRequest`, `Notification`, `AuditEvent`, `RunContext`
- **New/clarified fields on existing models:** Phase 1 is the first implementation, so nothing is "existing" yet. The following Phase-1-specific decisions refine plan.md §4.2 (and are recorded so later phases don't contradict them):
  - `DocumentRecord` is the **DB-backed canonical form**. Persisted fields (mapped to the `documents` table): `doc_id` (PK), `source_id`, `url`, `title`, `body_text`, `clean_text`, `published_date` (`datetime | None`, stored as UTC `DateTime`), `reference_number` (`str | None`), `document_type` (`DocumentType | None`, stored as its value string), `lang` (`str | None`), `char_count`, `word_count` (`int`), `content_hash` (`str`, indexed for `exists_by_content_hash`), `simhash` (`str | None`, **populated only in Phase 3**), `embedding_ids` (`list[str]`, JSON column, **empty `[]` in Phase 1**; populated Phase 3), `status` (`str`, default `"new"`), `created_at` / `updated_at` (`datetime`, DB-defaulted).
  - `NormalizedDocument` extends `ParsedDocument` with `clean_text`, `language`, `char_count`, `word_count` (per plan.md §4.2). `ParsedDocument` fields: `doc_id, url, title, body_text, published_date?, reference_number?, document_type?, lang?`.
  - `AuditEvent` persisted fields: `event_id` (PK, str/UUID), `ts` (`datetime`, DB-defaulted to now on insert), `stage` (`PipelineStage`), `actor` (`str`), `action` (`str`), `doc_id?` (`str | None`), `run_id?` (`str | None`), `metadata` (`dict[str, Any]`, JSON column).
  - A small **`DocumentChunk`** Pydantic model (`chunk_id, doc_id, ord, text, char_count`) is added to mirror the `document_chunks` table. It is **not** in plan.md §4.2's enumeration; recorded here as the minimal chunk record Phase 3's `Indexer` will extend (vector column is intentionally **not** added in Phase 1).
- Models that are **Pydantic-only** in Phase 1 (defined now because plan.md §4.2 lands the full vocabulary in Phase 1, but their DB tables/persistence arrive in later phases): `ClassificationResult`, `SummaryResult`, `RiskAssessment`, `ActionItem`, `ActionPlan`, `ApprovalRequest`, `Notification`, `RunContext`. Their persistence (e.g. `approvals`/`notifications`/`pipeline_runs`/`run_memory` tables) lands in Phases 5–6; Phase 1 only defines the types and the `run_memory`/`approvals`/`notifications` tables are **not** created.

## Database changes
First implementation of the schema (Phase 0 created no tables). Async SQLAlchemy (`create_async_engine` + `AsyncSession`). Phase 1 creates exactly **three** tables via `Base.metadata.create_all` in `db/schema.py` (no Alembic in Phase 1 — see "Rules"; migrations deferred):

- `documents` — ORM `DocumentRow`; columns as enumerated under `DocumentRecord` above. `content_hash` indexed (non-unique — dedup rejects exact dupes upstream; the store must not assume uniqueness). `doc_id` primary key.
- `document_chunks` — ORM `DocumentChunkRow`; `chunk_id` PK, `doc_id` FK→`documents.doc_id` (ON DELETE CASCADE), `ord` (`int`), `text` (`Text`), `char_count` (`int`), `created_at`. **No vector/embedding column** in Phase 1 (lands Phase 3).
- `audit_log` — ORM `AuditEventRow`; columns as enumerated under `AuditEvent` above. **Append-only**: no update/delete path is exposed or generated; the table receives inserts only.

Tables **not** created in Phase 1 (deferred to their owning phases): `pipeline_runs`, `run_memory` (Phase 6), `approvals` (Phase 5), `notifications` (Phase 5). Postgres is supported by the same async engine when `REGMON_DB_URL` points at a `postgresql+asyncpg://…` URL; the `asyncpg` driver is an optional extra (not installed by default; SQLite+`aiosqlite` is the default).

## Module contract
- **Inputs:**
  - `config.Settings` → engine factory reads `db_url`.
  - `DocumentRecord` (+ optional `Sequence[DocumentChunk]`) → `DocumentStore.upsert`.
  - `AuditEvent` → `AuditLog.append`.
  - Query params (`doc_id`, `content_hash`, `run_id`, `stage`, `jurisdiction`, `limit`/`offset`) → read methods.
- **Outputs:**
  - `DocumentRecord` (round-tripped) from `DocumentStore.get` / `DocumentStore.upsert`.
  - `list[DocumentRecord]` from `DocumentStore.list`.
  - `str | None` (existing `doc_id` or `None`) from `DocumentStore.exists_by_content_hash`.
  - `AuditEvent` from `AuditLog.append` (with DB-defaulted `ts`); `list[AuditEvent]` from `AuditLog.list`.
- **Key functions/classes (signatures match SQLAlchemy-async idioms):**
  - `config/settings.py`
    - `class Settings(BaseSettings)` — fields per `.env.example` (see "Provider abstraction"); `SettingsConfigDict(env_prefix="REGMON_", env_file=".env", extra="ignore")`.
    - `def get_settings() -> Settings` — process-wide cached settings (lru-cache-free; simple module-level singleton or `functools.lru_cache`).
  - `db/engine.py`
    - `def create_async_engine(settings: Settings | None = None) -> AsyncEngine`
    - `def session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]`
    - `async def init_db(engine: AsyncEngine) -> None` — `await conn.run_sync(Base.metadata.create_all)`.
  - `db/document_store.py`
    - `class DocumentStore`
      - `__init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None`
      - `async def upsert(self, record: DocumentRecord, chunks: Sequence[DocumentChunk] = ()) -> DocumentRecord`
      - `async def get(self, doc_id: str) -> DocumentRecord | None`
      - `async def exists_by_content_hash(self, content_hash: str) -> str | None`
      - `async def list(self, jurisdiction: Jurisdiction | None = None, limit: int = 100, offset: int = 0) -> list[DocumentRecord]`
  - `db/audit_log.py`
    - `class AuditLog`
      - `__init__(self, session_factory: async_sessionmaker[AsyncSession]) -> None`
      - `async def append(self, event: AuditEvent) -> AuditEvent` — insert-only.
      - `async def list(self, run_id: str | None = None, stage: PipelineStage | None = None, limit: int = 100) -> list[AuditEvent]`
- **Edge cases (explicit list):**
  - `doc_id` collision on `upsert` → upsert semantics (INSERT … ON CONFLICT DO UPDATE / SQLAlchemy `merge`) so a re-processed document updates rather than raises; `updated_at` advances.
  - `get(unknown_doc_id)` → returns `None` (no raise).
  - `exists_by_content_hash` miss → returns `None`; hit → returns the existing `doc_id`.
  - `AuditLog.append` is strictly insert-only; the class **exposes no `update`/`delete`/`remove` methods**. Re-appending the same `event_id` raises a clear error (duplicate PK) rather than silently overwriting (append-only integrity).
  - `AuditLog.list` returns events ordered by `ts` ascending; large tables are bounded by `limit` (default 100).
  - In-memory SQLite (`sqlite+aiosqlite:///:memory:`) for tests: each connection sees a fresh DB unless shared; `init_db` must run against the same engine/connection pool used by the store. Tests use a shared engine fixture (see "Testing plan").
  - `REGMON_DB_URL` is a sync-only sqlite URL (`sqlite:///…`) → engine factory must reject with a clear `ValueError` directing the user to `sqlite+aiosqlite:///…` rather than silently failing at first query. (Keeps async semantics non-negotiable.)
  - Postgres URL without `asyncpg` installed → import fails only when the engine connects; tests use sqlite, so the optional `postgres` extra is not required for `make test`.

## Provider abstraction
**No provider abstraction — deterministic module.** Phase 1 touches no LLM, embeddings, or vector store. The only backend choice is the DB (SQLite vs Postgres), both open-source, both reached through SQLAlchemy's native async API — no protocol/introduction layer is warranted.

One correctness note that prevents contradiction with the OSS-only seam established in Phase 0 (`01` spec, `.env.example`/`pyproject.toml`): `config.Settings` declares all `REGMON_*` keys documented in `.env.example` — including `llm_provider`, `llm_base_url`, `llm_model`, `embedding_provider`, `embedding_model`, `vector_store`, Slack/SMTP fields — as typed fields with the documented defaults, so there is a single source of truth for env config. **In Phase 1 only `db_url`, `dry_run`, and `risk_threshold` are read; the provider fields are declared-but-unwired** (consumed in Phases 3–7). No hosted/paid API appears (no `openai`-preset behavior, no `openai`-as-hosted-provider key); `openai` remains only the optional client SDK behind the `[local-llm]` extra (Phase 7), consistent with the 01 spec. plan.md §5.1/§10's lingering `openai` wording is **not** reconciled in this spec — that reconciliation remains deferred to a separate Plan-Mode sign-off (see memory: "plan.md OSS-only reconciliation still pending").

## Audit & observability
Phase 1 **defines** the audit vocabulary (`PipelineStage` enum, `AuditEvent`, `RunContext` models) and **implements the writer** (`AuditLog`) that every later stage uses. Phase 1 itself **emits no `AuditEvent`s during a run** and **contributes no `RunContext` counts/errors** — there is no orchestrator yet (Phases 6). Phase 1 unit tests exercise `AuditLog.append`/`list` directly to prove the writer. The `PipelineStage` values consumed by later phases' events are all enumerated now (plan.md §4.1). When stages later emit events, they will call `AuditLog.append(AuditEvent(stage=<PipelineStage.X>, …))`; that contract is fixed here.

## Files to change
- `pyproject.toml`
  - Add **core runtime deps** to `[project] dependencies`: `pydantic>=2.6`, `pydantic-settings>=2.2`, `sqlalchemy[asyncio]>=2.0`, `aiosqlite>=0.19`.
  - Add a new optional extra: `postgres = ["asyncpg>=0.29"]`.
  - (Optional, recommended) under `[tool.mypy]`, add `plugins = ["pydantic.mypy"]` to type-check model-field access for the large model set Phase 1 introduces. Marked optional so the implementer can decide; not a DoD gate.
- `.env.example`
  - Change the default `REGMON_DB_URL` from `sqlite:///regmon.db` (sync) to `sqlite+aiosqlite:///regmon.db` (async); expand the comment to state SQLite uses `aiosqlite` and Postgres uses `postgresql+asyncpg://…` (both async). Keeps the OSS-only var set unchanged.
- `src/regmon/models/__init__.py`, `src/regmon/db/__init__.py`, `src/regmon/config/__init__.py` — replace the one-line placeholder docstrings with re-exports of the public API (so `from regmon.models import DocumentRecord`, `from regmon.db import DocumentStore, AuditLog, init_db`, `from regmon.config import Settings, get_settings` all work).

## Files to create
- `src/regmon/models/enums.py` — `Jurisdiction`, `DocumentType`, `Urgency`, `RiskLevel`, `PipelineStage`, `ApprovalDecision`, `RunStatus` (plan.md §4.1).
- `src/regmon/models/documents.py` — `RegulatorySource`, `RawDocument`, `ParsedDocument`, `NormalizedDocument`, `DocumentRecord`, `DocumentChunk` (the document pipeline chain + chunk).
- `src/regmon/models/results.py` — `ClassificationResult`, `SummaryResult`, `RiskAssessment`, `ActionItem`, `ActionPlan`.
- `src/regmon/models/pipeline.py` — `ApprovalRequest`, `Notification`, `AuditEvent`, `RunContext`.
  > (Grouping is a recommendation; the binding contract is that `from regmon.models import <Name>` resolves for **every** enum/model named in plan.md §4.1/§4.2 + `DocumentChunk`. The implementer may re-balance the files as long as `models/__init__.py` re-exports the flat public API.)
- `src/regmon/config/settings.py` — `Settings`, `get_settings()`.
- `src/regmon/db/schema.py` — `Base(DeclarativeBase)`, `DocumentRow`, `DocumentChunkRow`, `AuditEventRow`.
- `src/regmon/db/engine.py` — `create_async_engine`, `session_factory`, `init_db`.
- `src/regmon/db/document_store.py` — `DocumentStore`.
- `src/regmon/db/audit_log.py` — `AuditLog`.
- `tests/conftest.py` — shared async in-memory SQLite fixture (`engine` + `init_db` + `session_factory`), reset per test.
- `tests/test_models.py` — every enum/model constructs/validates per "Testing plan".
- `tests/test_settings.py` — `Settings` defaults + env override.
- `tests/test_db_engine.py` — engine factory + `init_db` table creation.
- `tests/test_document_store.py` — upsert/get/exists/list round-trip + chunk persistence + ORM↔Pydantic fidelity.
- `tests/test_audit_log.py` — append/list + append-only invariant.

## New dependencies
- **Core runtime (added to `[project] dependencies`):** `pydantic>=2.6`, `pydantic-settings>=2.2`, `sqlalchemy[asyncio]>=2.0`, `aiosqlite>=0.19`.
- **New optional extra:** `postgres = ["asyncpg>=0.29"]` (declared now; required only when a Postgres URL is used/CI'd in Phase 7).
- **No new dev deps** (pytest/pytest-asyncio/pytest-cov already present from Phase 0; `asyncio_mode=auto` is already set).
- All additions are OSS; none is a hosted/paid API.

## Rules for implementation
- **Fully async for all DB I/O.** Use `create_async_engine`, `AsyncSession`, `async_sessionmaker`, and `async def` for every `DocumentStore`/`AuditLog`/`init_db` method. Tests run under the existing `asyncio_mode=auto` (no manual markers).
- **No provider abstraction needed** — deterministic module. (The DB is not a swappable *provider*; SQLAlchemy is the abstraction.)
- **No secrets/config read outside `config/Settings`.** `db/engine.py` reads `Settings.db_url`; `models/`/`db/` never call `os.environ` directly.
- **All DB writes go through `src/regmon/db/`.** No raw SQL or `engine.execute` in `models/` or anywhere else; use SQLAlchemy ORM (`select`/`insert`/`merge`) inside `document_store.py`/`audit_log.py`.
- **Audit log is append-only.** `AuditLog` exposes only `append` and `list`. No `update`/`delete`/`remove` API; the `audit_log` table is inserted into only. Duplicate `event_id` raises rather than overwrites.
- **Deterministic under tests.** Use in-memory SQLite with a shared engine fixture; no real network, no provider. (`mock` not applicable — no providers here; deterministic by construction.)
- **Type-hinted; passes `mypy` and `ruff`/`black`.** Strict typing on all public signatures (return `DocumentRecord | None`, `list[…]`, etc.). Optional: enable `pydantic.mypy` plugin (see "Files to change").
- **Surgical changes.** Do **not** touch `cli.py`, `scheduler.py`, `__main__.py`, `__init__.py` (package root), or any other-module stub (`crawler/`, `parser/`, …). Phase 1 edits only `models/`, `db/`, `config/`, `pyproject.toml`, `.env.example`, and tests. No CLI subcommands are added (those land in Phase 6); the existing `regmon` stub must still exit 0 (smoke tests stay green).
- **No migrations tool in Phase 1.** Schema init is `init_db()` → `Base.metadata.create_all`. Full Alembic migrations are intentionally deferred to a later phase to keep Phase 1 minimal (call-out for Plan Mode): if model churn is expected, Alembic can be added then; for now `create_all` on a fresh SQLite file is the documented bootstrap.
- **`REGMON_DRY_RUN`** is declared on `Settings` but trivially respected — Phase 1 has no outbound side effects to suppress.
- **OSS-only.** No hosted/paid LLM/embedding API is introduced (none is needed). `asyncpg`/`aiosqlite` are OSS drivers.

## Testing plan
- **Unit tests (no `@pytest.mark.integration`; Phase 1 exit is unit-level):**
  - `test_models.py`: each enum asserts its documented members (plan.md §4.1); each Pydantic model constructs with required fields and rejects invalid ones (`pytest.raises(ValidationError)`); optional fields default to `None`/empty; `DocumentRecord` carries the persisted fields and defaults `embedding_ids=[]`, `status="new"`, `simhash=None`; `NormalizedDocument` extends `ParsedDocument`. No mocking — pure model construction.
  - `test_settings.py`: `Settings()` defaults match `.env.example` (`dry_run=True`, `db_url="sqlite+aiosqlite:///regmon.db"`, `risk_threshold=60`, `llm_provider="mock"`, `vector_store="memory"`); overriding via explicit env (`monkeypatch.setenv`) changes the values; `extra="ignore"` tolerates unrelated env.
  - `test_db_engine.py`: `create_async_engine()` returns an `AsyncEngine`; `init_db` creates `documents`, `document_chunks`, `audit_log` (assert via `inspect(engine)` / `run_sync`); a sync `sqlite:///` URL passed to the factory raises `ValueError`. Uses the shared in-memory fixture.
  - `test_document_store.py`: **(Phase-1 exit gate)** upsert a fully-populated `DocumentRecord` (+ two `DocumentChunk`s), read it back via `get` and assert every field preserved (ORM↔Pydantic fidelity, including `metadata`-free scalars and empty `embedding_ids`); `exists_by_content_hash` returns the doc_id on hit / `None` on miss; upsert of the same `doc_id` updates (`updated_at` advances, `created_at` stable) rather than raising; `list` respects `jurisdiction` filter + `limit`/`offset`.
  - `test_audit_log.py`: **(Phase-1 exit gate)** `append` an `AuditEvent` and `list` it back ordered by `ts`; filter by `run_id` and `stage`; assert the second append of the same `event_id` raises (duplicate PK); **assert append-only at the API level** — `AuditLog` exposes no public `update`/`delete`/`remove`/`remove`-like method (e.g. `assert not hasattr(AuditLog, "update")`).
- **Mocks:** none needed — in-memory SQLite is real but local; no LLM/embeddings/http in Phase 1.
- **`tests/conftest.py`:** a session/module-scoped fixture yielding a shared in-memory `AsyncEngine` + initialized tables + `async_sessionmaker`, with a per-test `AsyncSession` (or a fresh `DocumentStore`/`AuditLog` bound to the shared factory). SQLite in-memory requires `connect_args={"check_same_thread": False}` and a shared pool (`StaticPool`) so `init_db` and the store see the same DB.
- **Integration test:** none added in Phase 1 (the `integration` marker remains unused; first integration scenarios arrive with Phase 2 crawler fixtures per plan.md §9).
- **Fixtures under `tests/fixtures/<jurisdiction>/`:** none (per-jurisdiction HTML/RSS/PDF fixtures land in Phase 2).

## Definition of done
- [ ] `pip install -e ".[dev]"` succeeds and pulls the new core deps (`pydantic`, `pydantic-settings`, `sqlalchemy[asyncio]`, `aiosqlite`); the package still imports.
- [ ] `make lint` passes (ruff + black `--check` + mypy) on the new `models/`/`db/`/`config/` code.
- [ ] `make test` passes — including the existing `tests/test_smoke.py` (subpackages still import, `cli.main([])==0`, `python -m regmon` and the console script exit 0).
- [ ] **Phase-1 exit gate A:** a test persists a fully-populated `DocumentRecord` via `DocumentStore.upsert` and reads it back unchanged via `DocumentStore.get` (plan.md §7 Phase 1 exit: "persist + retrieve a `DocumentRecord`").
- [ ] **Phase-1 exit gate B:** a test appends an `AuditEvent` via `AuditLog.append` and reads it back via `AuditLog.list`, and asserts `AuditLog` exposes no update/delete path (plan.md §7 Phase 1 exit: "append an `AuditEvent`"; append-only enforced).
- [ ] `init_db` creates exactly the `documents`, `document_chunks`, and `audit_log` tables (asserted via engine inspection).
- [ ] `Settings` reads `REGMON_DB_URL`/`REGMON_DRY_RUN`/`REGMON_RISK_THRESHOLD` with documented defaults; default `REGMON_DB_URL` is an async sqlite URL; `db/engine.py` rejects a sync `sqlite:///` URL with a clear `ValueError`.
- [ ] `.env.example` default `REGMON_DB_URL` updated to `sqlite+aiosqlite:///regmon.db`; `pyproject.toml` declares the core deps and the `postgres` extra.
- [ ] No new provider/extra is wired behaviorally (Phase 1 is deterministic); no `cli.py`/`scheduler.py`/other-module edits (surgical — verified via `git diff --stat`).
- [ ] (Deferred, orthogonal, *not* a Phase-1 gate) plan.md §5.1/§8/§10 OSS-only reconciliation remains pending separate Plan-Mode sign-off (per the 01 spec + memory).
