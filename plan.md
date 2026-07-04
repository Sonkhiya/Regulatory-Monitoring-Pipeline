# Regulatory Monitoring Pipeline — End-to-End Build Plan

> Canonical blueprint for building the Regulatory Monitoring Pipeline. Follow module-by-module during implementation.

## 1. Overview & Goals

A multi-agent system that:

1. **Crawls** regulatory sources (RBI, SEBI, FDA, EU AI Act) on a schedule.
2. **Parses & normalizes** fetched documents (HTML/PDF) into a canonical form.
3. **Deduplicates** across crawl runs (exact SHA-256 + SimHash near-duplicate).
4. **Indexes** content into a vector store (in-memory / FAISS / Chroma) for RAG.
5. **Classifies** each document by topic, function, and urgency.
6. **Summarizes** with a structured LLM summary.
7. **Assesses risk** via weighted scoring augmented by RAG context.
8. **Plans actions** — owner-assigned, deadline-driven follow-ups.
9. **Routes through a human-in-the-loop approval gate** for anything above a risk threshold.
10. **Notifies** via Slack / email with digests and alert dedup.
11. **Audits** every event to an append-only log.

**System quality goals:** runs fully offline by default (mock LLM + embeddings), idempotent crawl cycles, observable state, and a clear HITL gate so humans never lose control of outbound actions.

## 2. Architecture & Data Flow

```
Crawler ─► Parser ─► Normalizer ─► Dedup ─►┬─► Classification ─► Summarization ─► RAG Indexing
                                            │                                         │
                                            │                                         ▼
                                            └──────────────────────────────► Risk Assessment (uses RAG)
                                                                                         │
                                                                                         ▼
                                                                          Action Planner ─► Approval Gate (HITL) ─► Notifier
                                                                                         │
                                                                                         ▼
                                                                          Orchestrator persists state + Audit Log
```

The **Pipeline Orchestrator** wires these stages into a single async graph with persistent **run memory** (every run records start/end, per-stage status, counts, and resumable state). All stages write to cross-cutting stores: Document Store, Audit Log, Approvals, Pipeline Memory.

```
┌─────────────────────────────────────────────────────────────────────┐
│                         Pipeline Orchestrator                        │
│                                                                     │
│  ┌──────────┐   ┌────────┐   ┌───────────┐   ┌──────────────────┐ │
│  │ Crawler  │──>│ Parser │──>│ Normalizer│──>│ Deduplication    │ │
│  │ Agent    │   │ Agent  │   │           │   │ Engine           │ │
│  └──────────┘   └────────┘   └───────────┘   └────────┬─────────┘ │
│       │                                                │           │
│       │ (adapters: RBI, SEBI, FDA, EU)     unique docs │           │
│       │                                                ▼           │
│  ┌──────────┐   ┌────────────┐   ┌──────────┐   ┌──────────────┐ │
│  │ Notifier │<──│ Approval   │<──│ Action  │<──│ Risk         │ │
│  │ Agent    │   │ Gate (HITL)│   │ Planner  │   │ Assessment   │ │
│  └──────────┘   └────────────┘   └──────────┘   └──────┬───────┘ │
│       │                                                  │         │
│       │ (Slack, Email)                                   │         │
│       │                                   ┌──────────────┴───────┐ │
│       │                                   │ Classification Agent │ │
│       │                                   │ + Summarization      │ │
│       │                                   │ + RAG Indexing       │ │
│       │                                   └──────────────────────┘ │
│  ┌────┴────────────────────────────────────────────────────────┐ │
│  │              Cross-cutting: SQLite/Postgres DB               │ │
│  │  Document Store │ Audit Log │ Pipeline Memory │ Approvals    │ │
│  └─────────────────────────────────────────────────────────────┘ │
└─────────────────────────────────────────────────────────────────────┘
```

## 3. Supported Jurisdictions

| Jurisdiction | Regulator | Sources |
|-------------|-----------|---------|
| RBI | Reserve Bank of India | Notifications, Press Releases |
| SEBI | Securities and Exchange Board of India | Legal Circulars |
| FDA | U.S. Food and Drug Administration | Press RSS, Federal Register |
| EU AI Act | European Commission | AI Act Newsroom |

## 4. Data Models (`src/regmon/models/`)

### 4.1 Enums
- `Jurisdiction` — `RBI | SEBI | FDA | EU_AI_ACT`
- `DocumentType` — `NOTIFICATION | PRESS_RELEASE | CIRCULAR | RSS_ITEM | REGULATION | NEWS`
- `Urgency` — `LOW | MEDIUM | HIGH | CRITICAL`
- `RiskLevel` — `LOW | MEDIUM | HIGH | CRITICAL`
- `PipelineStage` — `CRAWL | PARSE | NORMALIZE | DEDUP | CLASSIFY | SUMMARIZE | INDEX | RISK | PLAN | APPROVE | NOTIFY`
- `ApprovalDecision` — `APPROVED | REJECTED | DEFERRED | AUTO_APPROVED`
- `RunStatus` — `PENDING | RUNNING | SUCCEEDED | FAILED | PARTIAL`

### 4.2 Core Pydantic models
- `RegulatorySource` — `id, jurisdiction, name, listing_url, feed_url?, adapter, crawl_policy`
- `RawDocument` — `source_id, url, fetched_at, http_status, content_bytes, headers, etag?, last_modified?`
- `ParsedDocument` — `doc_id, url, title, body_text, published_date?, reference_number?, document_type?, lang?`
- `NormalizedDocument` — extends Parsed with `clean_text, language, char_count, word_count`
- `DocumentRecord` (DB-backed) — canonical persisted form; includes `content_hash, simhash, embedding_ids[], status`
- `ClassificationResult` — `topics[], functions[], urgency, confidence, rationale`
- `SummaryResult` — `executive_summary, key_points[], affected_business_areas[], compliance_implications`
- `RiskAssessment` — `risk_level, score (0-100), drivers[], rag_citations[]`
- `ActionItem` — `action_id, title, description, owner, team, priority, due_date, depends_on[]`
- `ActionPlan` — `doc_id, actions[]`
- `ApprovalRequest` — `doc_id, risk_assessment, action_plan, requested_at, decided_at?, decision?, decision_by?, decision_note?`
- `Notification` — `channel, recipient, subject, body, doc_id, sent_at, dedup_key`
- `AuditEvent` — `event_id, ts, stage, actor, action, doc_id?, run_id?, metadata{}`
- `RunContext` — `run_id, started_at, ended_at?, status, stage_states{}, counts{}, errors[]`

### 4.3 DB schema (SQLAlchemy, SQLite default / Postgres optional)
Tables: `documents`, `document_chunks` (for embeddings), `audit_log`, `pipeline_runs`, `run_memory`, `approvals`, `notifications`. All append/immutable where noted; audit log is strictly append-only.

## 5. Module Contracts

Each module: **responsibility → inputs → outputs → key functions → edge cases.**

### 5.1 `config/` — Settings & source registry
- `Settings` (pydantic-settings) loads from env + `.env`. Keys: `REGMON_DRY_RUN`, `REGMON_DB_URL`, `REGMON_EMBEDDING_PROVIDER`, `REGMON_LLM_PROVIDER`, `REGMON_VECTOR_STORE`, `REGMON_RISK_THRESHOLD`, Slack/email creds, OpenAI key.
- `SourceRegistry` loads `sources.yaml` → list of `RegulatorySource`.
- Provider presets: `mock` (default, offline), `openai`.

### 5.2 `crawler/` — Async fetch + adapters
- `AsyncFetcher` — `httpx.AsyncClient`, retry/backoff (exponential), timeout, conditional fetch (ETag/Last-Modified 304 handling), respects `robots.txt` via `urllib.robotparser`, per-host rate limit (token bucket).
- `RateLimiter` — min interval per host, jittered.
- `RobotsCache` — cached robots.txt per host with TTL.
- `Adapters` (`rbi.py`, `sebi.py`, `fda.py`, `eu_ai_act.py`) — each implements `list_entries(since=None) -> Iterable[RemoteEntry]` (HTML listing scraper + RSS/Atom feed parser via `feedparser`) and `fetch(entry) -> RawDocument`.
- `CrawlerAgent` (LLM-agent semantics optional) — orchestrates fetch queue, dedup against known-seen-URLs set, emits `RawDocument`s.

### 5.3 `parser/` — Extraction & metadata
- `HTMLParser` — `BeautifulSoup` → title + body; strips nav/footer/script.
- `PDFParser` — `pypdf` → text extraction, table-of-contents hints.
- `MetadataExtractor` — regex/dateparser for `published_date` and `reference_number` patterns per jurisdiction.

### 5.4 `normalize/` — Cleaning
- `EncodingRepair` — `ftfy`/chardet fallback.
- `BoilerplateStripper` — heuristic removal of repeated site chrome across runs.
- `LanguageDetector` — `langdetect` or heuristic; tag `lang`.
- Outputs `NormalizedDocument` with token stats.

### 5.5 `dedup/` — Exact + near-duplicate
- `ContentHasher` — SHA-256 over normalized text → exact dup flag.
- `SimHashIndex` — 64-bit SimHash, Hamming-distance band (≤3) → near-dup cluster; persists fingerprints for cross-run recall.
- API: `is_duplicate(doc) -> (bool, duplicate_of_doc_id?)`.

### 5.6 `embeddings/` — Chunking, providers, stores, indexer
- `Chunker` — recursive/sentence-aware chunking with overlap; configurable size/overlap.
- `EmbeddingProvider` protocol — `mock` (deterministic hash-vector), `openai` (`text-embedding-3-small`).
- `VectorStore` protocol — `InMemoryStore`, `FAISSStore` (`.[faiss]`), `ChromaStore` (`.[chroma]`).
- `Indexer` — upsert chunks + vectors for a `NormalizedDocument`; returns `embedding_ids[]`. Lazy backend init.

### 5.7 `rag/` — Semantic search service
- `RAGSearch` — `search(query, jurisdiction?, top_k, score_threshold) -> [Citation(doc_id, chunk, score)]`.
- Citations include doc metadata + snippet + score. Honors jurisdiction filter and threshold floor.

### 5.8 `classification/` — Rule-based (LLM optional)
- `RuleClassifier` — keyword/regex lexicons per jurisdiction → `topics[]` (e.g. AML, KYC, derivatives), `functions[]` (e.g. reporting, disclosure), `urgency` (deadline-driven escalation).
- Extensible to LLM provider for ambiguous cases (mock returns canned).

### 5.9 `summarization/` — Structured summaries
- `Summarizer` protocol — `mock` (template from key sentences), `openai` (structured JSON via function/tool calling → `SummaryResult`).
- Output fields: `executive_summary`, `key_points[]`, `affected_business_areas[]`, `compliance_implications`.

### 5.10 `risk/` — Weighted scoring + RAG context
- `RiskScorer` — weighted: `urgency` (x3), `penalty_keywords` (x2), `scope`(breadth) (x1.5), `deadline_proximity` (x2) → 0-100 → `RiskLevel` buckets.
- `RiskAgent` — augments with top-K RAG citations of comparable past regs to justify the score in `drivers[]` and `rag_citations[]`.
- Threshold `REGMON_RISK_THRESHOLD` triggers the approval gate.

### 5.11 `actions/` — Action planner
- `ActionPlanner` — maps risk+summary → `ActionItem[]` using templates per (jurisdiction, topic). Assigns `owner`/`team` from an ownership matrix (`config/ownership.yaml`), computes `due_date` from urgency/deadlines, sets `depends_on[]`.
- Templates cover common cases: "review circular", "update policy doc", "customer comms", "legal sign-off", "system config change".

### 5.12 `approval/` — Human-in-the-loop gate
- `ApprovalGate` — if `risk_level >= threshold`, create `ApprovalRequest` and persist; **block** downstream notify until decided. Below threshold → `AUTO_APPROVED` (audit-recorded).
- Persisted decisions table; supports `APPROVED | REJECTED | DEFERRED`. DEFERRED re-enters queue on next run with a reason.
- CLI/programmatic decision entry (`regmon approve <request_id>`).

### 5.13 `notifications/` — Channels + digest + dedup
- `SlackNotifier` — webhook client; rich digest block per run; alert dedup via `dedup_key` (doc_id+action) within a TTL window to avoid re-alerting.
- `EmailNotifier` — SMTP (`aiosmtplib`); HTML+plain digest; per-team routing from ownership matrix.
- Both respect `REGMON_DRY_RUN` (log instead of send) and only fire on approved actions.

### 5.14 `pipeline/` — Orchestrator + state
- `PipelineOrchestrator` — async graph; per-run `RunContext`; stage transitions emit `AuditEvent`; supports resume from last completed stage; collects counts and errors.
- `RunMemory` — persistent resume cursor + stage snapshots in `pipeline_runs`/`run_memory`.

### 5.15 `scheduler.py` + `cli.py` (+ `__main__.py`)
- `regmon sources` — list configured sources.
- `regmon run [--loop --interval N]` — one-shot or continuous.
- `regmon backfill [--since DATE]` — bypass dedup for historical replay.
- `regmon status` — show last run + pending approvals.
- `regmon approve <id> [--decision APPROVED|REJECTED|DEFERRED] [--note ...]`.
- Scheduler wraps orchestrator for `--loop`.

### 5.16 `db/` — Persistence
- `engine.py` — SQLAlchemy engine factory (SQLite file default; Postgres via `REGMON_DB_URL`).
- `document_store.py` — CRUD for `DocumentRecord` + chunks.
- `audit_log.py` — append-only `AuditEvent` writer + reader.

## 6. Feature Specs (expanded)

- **Async crawl with fairness:** per-host token bucket + jittered retry; 304 short-circuit; robots.txt enforced and cached; crawl budget per source.
- **Source adapters:** RBI notifications + press releases; SEBI legal circulars; FDA press RSS + Federal Register; EU AI Act newsroom. Each adapter isolated and individually testable with recorded fixtures.
- **Parse HTML & PDF:** robust fallback chain; metadata extraction per jurisdiction patterns.
- **Normalization:** encoding repair, boilerplate stripping, language tagging, hidden-char removal.
- **Dedup:** SHA-256 exact + SimHash near-duplicate (Hamming ≤3), persistent fingerprints across runs.
- **Embeddings + vector search:** chunking w/ overlap; mock (offline) + OpenAI; in-memory/FAISS/Chroma backends chosen via extras.
- **RAG:** citation-bearing search with jurisdiction filter + score threshold.
- **Classification:** rule-based topic/function/urgency; LLM-upgradable.
- **Summarization:** structured mock + OpenAI outputs.
- **Risk:** weighted scoring + RAG context + rationale; threshold-controlled gate.
- **Action planner:** ownership matrix, deadline calc, dependency graph, templates.
- **HITL approval:** persisted decisions, DEFERRED re-queue, audit-everywhere; auto-approve below threshold.
- **Notifications:** Slack + email, digest, dedup, dry-run safety.
- **Orchestrator:** resumable runs, persistent memory, full audit.
- **Scheduler + CLI:** `run|backfill|status|sources|approve`.
- **Audit log:** append-only across all stages.
- **Provider abstractions:** everything swaps via env (mock default → fully offline).

## 7. Phased Build Roadmap

### Phase 0 — Scaffolding & tooling
- `pyproject.toml` (extras: `dev`, `faiss`, `chroma`, `openai`), `src/regmon` package skeleton (empty modules), `.env.example`, `Makefile` (install/lint/format/test/test-cov/hooks/clean), pre-commit config, `.github/workflows` (lint + test matrix + integration), ruff/black/mypy config, `pytest` markers.
- **Exit:** `make lint` + `make test` pass on an empty-but-importable package.

### Phase 1 — Core data + persistence
- `models/` (enums + Pydantic models), `db/` (engine, document_store, audit_log), migrations/init schema.
- **Exit:** persist + retrieve a `DocumentRecord`; append an `AuditEvent`; unit tests green.

### Phase 2 — Crawler + adapters + parser + normalize
- `crawler/`, `parser/`, `normalize/` with recorded HTML/PDF fixtures per adapter; robots + rate limit.
- **Exit:** `regmon run` fetches fixtures → produces `NormalizedDocument`s end-to-end; offline tests with `httpx.MockTransport`.

### Phase 3 — Dedup + embeddings + RAG
- `dedup/`, `embeddings/` (mock provider, in-memory store), `rag/`.
- **Exit:** identical content deduped; near-dup clustered; RAG returns cited results.

### Phase 4 — Intelligence: classification + summarization + risk + actions
- `classification/`, `summarization/` (mock), `risk/`, `actions/` + ownership matrix.
- **Exit:** a normalized doc → classification → summary → risk assessment → action plan, all via mocks offline.

### Phase 5 — Approval gate + notifications
- `approval/`, `notifications/` (Slack + email, dry-run). Integration with orchestrator.
- **Exit:** high-risk doc blocks notifications until approved; dry-run logs instead of sending.

### Phase 6 — Orchestrator + scheduler + CLI
- `pipeline/` (graph, run memory, resume), `scheduler.py`, `cli.py` (`run|backfill|status|sources|approve`).
- **Exit:** full `regmon run` over fixtures produces classified/summarized/risked/actioned/approved/notified/audited records.

### Phase 7 — Provider integrations & hardening
- OpenAI provider paths; FAISS/Chroma backends; Postgres path; CI integration tests; coverage gates.
- **Exit:** `pytest -m integration` green; `pip install -e ".[faiss]"` / `.[chroma]` / `.[openai]` all functional.

## 8. Project Layout

```
src/regmon/
├── __init__.py, __main__.py, cli.py, scheduler.py
├── config/          # Settings, secrets, source registry
├── models/          # Pydantic domain models and enums
├── crawler/         # Async fetcher, rate limiter, robots.txt, adapters
├── parser/          # HTML/PDF extraction, metadata (dates, ref numbers)
├── normalize/       # Encoding repair, boilerplate strip, language detect
├── dedup/           # Content hashing, SimHash near-duplicate engine
├── embeddings/      # Chunking, providers, vector stores, indexer
├── rag/             # Semantic search service with citations
├── classification/  # Rule-based + LLM topic/function classifier
├── summarization/   # Structured LLM summaries (mock + OpenAI)
├── risk/            # Risk scoring, rationale, assessment agent
├── actions/         # Action planner with templates and due dates
├── approval/        # Human-in-the-loop gate with persisted decisions
├── notifications/   # Slack/email channels, digest formatting, dedup
├── pipeline/        # Orchestrator, state tracking, run context
└── db/              # SQLAlchemy engine, document store, audit log
tests/               # Unit + integration test suite
.github/workflows/   # CI pipeline (lint, test matrix, integration)
```

## 9. Testing Strategy
- **Unit:** every module; mocks for LLM/embeddings/http. In-memory SQLite. `httpx.MockTransport` for crawler.
- **Integration** (`@pytest.mark.integration`): full pipeline over recorded fixtures; approval flow; notification dry-run; vector store backends.
- **Coverage:** `pytest --cov=regmon`, gate in CI.
- **Fixtures:** per-adapter recorded HTML/RSS/PDF under `tests/fixtures/<jurisdiction>/`.
- Determinism: mock providers must be deterministic to keep CI stable.

## 10. Configuration & Ops

All settings are read from environment variables (see `.env.example`). The
pipeline ships with `mock` LLM and embedding providers so it runs fully
offline by default. Set `REGMON_DRY_RUN=true` to suppress outbound notifications.

- `.env.example` documents all `REGMON_*` vars incl. provider selection, DB URL, risk threshold, Slack/email, OpenAI key.
- `REGMON_DRY_RUN=true` suppresses outbound notifications.
- Default DB: `sqlite:///regmon.db`; Postgres via `REGMON_DB_URL`.
- Default providers: `mock` / in-memory store → runs fully offline.

### Optional Extras
```bash
pip install -e ".[faiss]"    # FAISS vector store backend
pip install -e ".[chroma]"   # Chroma vector store backend
pip install -e ".[openai]"   # OpenAI embeddings + LLM
```

### Make Targets
| Target | Description |
|--------|-------------|
| `make install` | Install package with dev dependencies |
| `make lint` | Run ruff + black (check) + mypy |
| `make format` | Auto-format with black + ruff --fix |
| `make test` | Run the test suite |
| `make test-cov` | Run tests with coverage report |
| `make hooks` | Install pre-commit hooks |
| `make clean` | Remove caches and build artifacts |

### CLI
```bash
regmon sources                  # list configured sources
regmon run                      # one-shot pipeline run
regmon run --loop --interval 60 # continuous mode
regmon status                   # check pipeline state
regmon backfill                 # re-process ignoring dedup
regmon approve <id> [--decision APPROVED|REJECTED|DEFERRED] [--note ...]
```

## 11. Verification (how to confirm the build works)
1. `make lint && make test` — all green offline.
2. `regmon sources` — lists RBI/SEBI/FDA/EU.
3. `regmon run` over fixtures → produces records with classification, summary, risk, actions; high-risk items create pending approvals.
4. `regmon status` shows last run + pending approvals.
5. `regmon approve <id> --decision APPROVED` → notification logged (dry-run).
6. Re-run `regmon run` → dedup removes already-seen docs; near-dups clustered.
7. `pytest -m integration` green; swap to `.[openai]`/`.[faiss]` and rerun integration.

## 12. License
MIT
