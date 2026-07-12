# Spec: Parser HTML/PDF

## Overview
This is **Phase 2 (part)** of `plan.md §7` — the document parsing layer that extracts structured text and jurisdiction-specific metadata from `RawDocument` bytes (HTML/PDF) produced by the crawler. It implements the `parser/` package: an `HTMLParser` using `BeautifulSoup` to strip boilerplate (nav, footer, script, style) and extract title/body, a `PDFParser` using `pypdf` for PDF text extraction with TOC hints, and a `MetadataExtractor` that applies jurisdiction-specific regex/dateparser patterns to derive `published_date`, `reference_number`, and `document_type`. This module sits between the crawler (Phase 2a) and the normalizer (Phase 2b); Phase 3+ cannot run without `ParsedDocument` output.

## Depends on
- **Phase 0 — Scaffolding (complete).** `pyproject.toml`, `Makefile`, `ruff`/`black`/`mypy` config, empty package skeleton, `.env.example`.
- **Phase 1 — Core data + persistence (spec `02-data-models-persistence`, complete).** Provides `RawDocument`, `ParsedDocument`, `DocumentType`, `Jurisdiction` enums, and `RegulatorySource` config.
- **Phase 2a — Crawler + adapters (spec `03-crawler-adapters`, complete).** Produces `RawDocument` objects with `content_bytes` (HTML or PDF) from the four jurisdiction adapters (RBI, SEBI, FDA, EU AI Act).
- `plan.md §5.3` explicitly scopes `parser/` within Phase 2 alongside `crawler/` and `normalize/`.

## Data models touched
Consumes / produces models from `plan.md §4.2` (already defined in Phase 1):

- **Consumes:** `RawDocument` — `source_id`, `url`, `content_bytes`, `headers` (for `Content-Type` sniffing).
- **Produces:** `ParsedDocument` — `doc_id` (SHA-256 of URL + fetched_at), `url`, `title`, `body_text`, `published_date?`, `reference_number?`, `document_type?`, `lang?`.
- **No new Pydantic models or enums** introduced by this module.

## Database changes
**No database changes.** This module performs stateless text extraction + metadata parsing only. It emits `ParsedDocument` objects; the caller (pipeline orchestrator, Phase 6) persists them via `DocumentStore` (Phase 1) after normalization (Phase 2b). No new tables, columns, or indexes.

## Module contract
- **Inputs:**
  - `RawDocument` objects from `CrawlerAgent` (or test fixtures).
  - `Jurisdiction` enum (from `RawDocument.source_id` via `SourceRegistry`) to select metadata extraction patterns.
- **Outputs:**
  - `ParsedDocument` per successfully parsed `RawDocument`.
  - Parse errors are logged; failed parses return `None` (caller decides to skip or record error).
- **Key functions/classes (signatures match `plan.md §5.3` style):**
  - `parser/html_parser.py`:
    - `class HTMLParser`
      - `__init__(strip_selectors: list[str] | None = None)` — default strips `nav`, `footer`, `script`, `style`, `header`, `aside`, `[role="navigation"]`, `.sidebar`, `.nav`, `.footer`.
      - `parse(html: str, url: str) -> tuple[str, str]` — returns `(title, body_text)`; title from `<title>` or first `<h1>`, body from `<main>`, `<article>`, or `<body>` after stripping selectors.
      - `extract_text(soup: BeautifulSoup) -> str` — utility to get clean text from a `BeautifulSoup` node.
  - `parser/pdf_parser.py`:
    - `class PDFParser`
      - `__init__(extract_toc: bool = True)` — if true, attempts to extract table-of-contents entries as metadata hints.
      - `parse(pdf_bytes: bytes) -> tuple[str, dict[str, Any]]` — returns `(full_text, metadata)` where `metadata` may include `toc_entries: list[dict]`, `page_count`, `is_scanned` heuristic.
  - `parser/metadata.py`:
    - `class MetadataExtractor`
      - `__init__(jurisdiction: Jurisdiction)` — loads pattern config for that jurisdiction.
      - `extract(text: str, url: str) -> dict[str, Any]` — returns `{"published_date": datetime | None, "reference_number": str | None, "document_type": DocumentType | None, "language": str | None}`.
      - Patterns per jurisdiction (configurable via `config/parser_patterns.yaml` loaded at init):
        - **RBI:** `published_date` — regex for "DD MMM YYYY", "DD/MM/YYYY"; `reference_number` — `RBI/\d{4}-\d{2}/[A-Z]+/\d+` or `DBR\.\w+\.No\.\d+/\d+\.\d+\.\d+/\d{4}-\d{2}`; `document_type` — "Notification" vs "Press Release" via URL/title keywords.
        - **SEBI:** `published_date` — "DD MMM YYYY", "MM/DD/YYYY"; `reference_number` — `SEBI/HO/\w+/\d+/CIR/\d{4}/\d+`; `document_type` — "CIRCULAR".
        - **FDA:** `published_date` — RSS `<pubDate>` or Federal Register `publication_date`; `reference_number` — FR citation `XX FR YYYYY` or `RIN xxxx-xx`; `document_type` — "RSS_ITEM" vs "REGULATION".
        - **EU AI Act:** `published_date` — ISO date in meta/article; `reference_number` — "Article X", "Annex X", "Recital X"; `document_type` — "REGULATION" or "NEWS".
  - `parser/__init__.py`:
    - `class ParserAgent` (orchestrator, mirrors `CrawlerAgent` style)
      - `__init__(html_parser?, pdf_parser?, metadata_extractor_factory?)`
      - `async parse(raw_doc: RawDocument, jurisdiction: Jurisdiction) -> ParsedDocument | None` — dispatches to HTML/PDF parser based on `Content-Type` header or magic bytes, then runs metadata extraction.
      - `async parse_batch(raw_docs: list[RawDocument], jurisdictions: list[Jurisdiction]) -> list[ParsedDocument]` — concurrent with semaphore.
    - `def detect_content_type(content_bytes: bytes, headers: dict[str, str] | None = None) -> Literal["html", "pdf", "unknown"]` — sniff `Content-Type` header first, then magic bytes (`%PDF`).
- **Edge cases (explicit list):**
  - `RawDocument.content_bytes` empty → return `None`, log warning, caller increments error count.
  - HTML with no `<title>` or `<h1>` → title = URL path or "Untitled".
  - HTML body extraction yields < 100 chars after stripping → treat as likely boilerplate-only; log warning, still return `ParsedDocument` (normalizer handles downstream).
  - PDF is scanned/image-based (no extractable text) → `metadata["is_scanned"] = True`, `body_text = ""`, log warning.
  - `Content-Type` missing/incorrect → fall back to magic bytes; if both fail, default to HTML parser (lenient).
  - Metadata extraction finds no date/ref → fields stay `None` (normalizer/classifier handles missing).
  - Jurisdiction not in pattern config → use generic dateparser + empty patterns (no crash).
  - Concurrent parsing limit respected via `asyncio.Semaphore` (default 10).

## Provider abstraction
**No provider abstraction — deterministic module.** All parsing uses OSS libraries (`beautifulsoup4`, `lxml`, `pypdf`, `dateparser`, `ftfy` for later normalize phase). No LLM, embedding, or vector-store providers are invoked. The parser is fully offline and deterministic given the same input bytes. `REGMON_LLM_PROVIDER` / `REGMON_EMBEDDING_PROVIDER` are not read here (Phase 3–7 only).

## Audit & observability
- **No `AuditEvent` emitted by this module.** The orchestrator (Phase 6) emits `PipelineStage.PARSE` events when it wraps the parser. `ParserAgent` returns parse stats (count, errors, duration) for the caller to include in `RunContext.counts` and `RunContext.errors`.
- **Logging:** `ParserAgent` uses `logging.getLogger(__name__)` at INFO for batch start/complete, WARNING for parse failures (empty body, scanned PDF, missing content-type), DEBUG for per-document parse path (HTML vs PDF, metadata found).

## Files to change
- `pyproject.toml` — add **core runtime deps** (already declared in Phase 2a spec; verify present): `beautifulsoup4>=4.12`, `lxml>=5.0`, `pypdf>=4.0`, `dateparser>=1.2`, `ftfy>=6.1` (for later normalize phase but declared here), `pyyaml>=6.0` (for pattern config).
- `.env.example` — no new vars.
- `src/regmon/parser/__init__.py` — re-export public API: `HTMLParser`, `PDFParser`, `MetadataExtractor`, `ParserAgent`, `detect_content_type`.

## Files to create
All new files (parser package did not exist beyond `__init__.py`):
- `src/regmon/parser/html_parser.py` — `HTMLParser`
- `src/regmon/parser/pdf_parser.py` — `PDFParser`
- `src/regmon/parser/metadata.py` — `MetadataExtractor` + jurisdiction pattern config loader
- `src/regmon/parser/__init__.py` — `ParserAgent`, `detect_content_type`, re-exports
- `config/parser_patterns.yaml` — jurisdiction-specific regex/date patterns (loaded by `MetadataExtractor`)
- `tests/fixtures/parser/` — minimal test fixtures:
  - `rbi_notification.html`, `rbi_press.html`, `sebi_circular.html`, `fda_press.xml`, `fda_fr.json`, `eu_article.html`, `sample.pdf` (small text PDF), `scanned.pdf` (empty text PDF for scanned heuristic test)
- `tests/conftest.py` — add `parser_agent` fixture (instantiated `ParserAgent`), `sample_raw_documents` fixture (list of `RawDocument` with fixtures).
- `tests/test_parser_html.py` — `HTMLParser` unit tests: title/body extraction, boilerplate stripping, empty/edge-case HTML.
- `tests/test_parser_pdf.py` — `PDFParser` unit tests: text extraction, TOC hints, scanned PDF detection, empty PDF.
- `tests/test_parser_metadata.py` — `MetadataExtractor` per-jurisdiction tests against fixture texts: date/ref/type extraction correctness.
- `tests/test_parser_agent.py` — `ParserAgent` orchestration: content-type dispatch, concurrent batch parse, error handling, stats collection.

## New dependencies
- **Core runtime (added to `[project] dependencies` in `pyproject.toml`):** `beautifulsoup4>=4.12`, `pypdf>=4.0`, `dateparser>=1.2`, `ftfy>=6.1`, `pyyaml>=6.0`, `lxml>=5.0` (already in crawler deps; ensure present).
- **No new optional extras.** All deps are OSS and required for parser to function.
- **Dev deps unchanged** (pytest/pytest-asyncio/pytest-cov/httpx already present).

## Rules for implementation
- **Fully async** where I/O occurs (PDF parsing is CPU-bound; run in `asyncio.to_thread` or process pool if large; for Phase 2 fixtures, `asyncio.to_thread` is sufficient).
- **Provider protocol only for test injection** — `ParserAgent` accepts `html_parser`, `pdf_parser`, `metadata_extractor_factory` as constructor args; tests can pass mocks.
- **No secrets/config outside `config/Settings`** — parser reads nothing from `os.environ`; jurisdiction patterns loaded from `config/parser_patterns.yaml` (bundled in package).
- **All DB writes through `src/regmon/db/`** — this module does **zero** DB writes; emits `ParsedDocument` for orchestrator.
- **Audit log append-only** — not applicable here (no `AuditEvent` emission); Phase 6 owns that.
- **Deterministic behavior** — same input bytes always produce same `ParsedDocument` (no randomness, no external API calls).
- **Type-hinted, passes `mypy` and `ruff`** — strict signatures; `ignored_missing_imports` for optional deps in `mypy` config (already set for `lxml`, `pypdf`, `dateparser`, `ftfy`, `bs4`, `yaml`).
- **Respects `REGMON_DRY_RUN`** — not applicable (no outbound side effects).

## Testing plan
- **Unit tests (no `@pytest.mark.integration`):**
  - `test_parser_html.py`:
    - `HTMLParser.parse` on fixture HTML → title from `<h1>`, body from `<main>` with nav/footer/script stripped.
    - Empty HTML → title "Untitled", body "".
    - HTML with only boilerplate → logs warning, returns minimal body.
    - Custom `strip_selectors` respected.
  - `test_parser_pdf.py`:
    - `PDFParser.parse` on `sample.pdf` → non-empty text, page_count > 0.
    - `extract_toc=True` → `metadata["toc_entries"]` list present.
    - `scanned.pdf` → `metadata["is_scanned"] = True`, empty text.
    - Empty PDF → empty text, page_count = 0.
  - `test_parser_metadata.py` (parameterized per jurisdiction):
    - RBI notification text → `published_date` parsed, `reference_number` matches `RBI/2024-25/...`, `document_type = NOTIFICATION`.
    - RBI press release → `document_type = PRESS_RELEASE`.
    - SEBI circular → `reference_number` matches `SEBI/HO/...`, `document_type = CIRCULAR`.
    - FDA RSS item → `document_type = RSS_ITEM`, date from `<pubDate>`.
    - FDA Federal Register → `document_type = REGULATION`, `reference_number` = FR citation.
    - EU AI Act article → `document_type = REGULATION`, `reference_number` = "Article 5".
    - Missing jurisdiction → falls back to generic `dateparser`, no crash.
  - `test_parser_agent.py`:
    - `ParserAgent.parse` dispatches HTML → `HTMLParser`, PDF → `PDFParser` (via `detect_content_type`).
    - `Content-Type: application/pdf` header honored over magic bytes.
    - Magic bytes `%PDF` overrides missing header.
    - `parse_batch` with semaphore=2 processes 5 docs, max 2 concurrent.
    - Failed parse (empty bytes) returns `None`, logs warning, other docs succeed.
    - Stats returned: `parsed`, `failed`, `duration`.
- **Fixtures under `tests/fixtures/parser/`:**
  - Minimal HTML/PDF samples per jurisdiction (re-use some crawler fixtures where appropriate).
  - `sample.pdf` — 2-page text PDF with TOC.
  - `scanned.pdf` — 1-page PDF with no extractable text (create via `pypdf` in test setup or commit tiny binary).
- **Integration test:** Not in this spec (Phase 2 exit says "offline tests with fixtures"); full pipeline integration with crawler+parser+normalize is Phase 2 end-to-end but not a separate `@pytest.mark.integration` here.

## Definition of done
- [ ] `pip install -e ".[dev]"` succeeds; new deps (`beautifulsoup4`, `pypdf`, `dateparser`, `ftfy`, `pyyaml`) installed.
- [ ] `make lint` passes (ruff + black `--check` + mypy) on new `parser/` code.
- [ ] `make test` passes — all new unit tests green, existing Phase 0/1/2a tests still green.
- [ ] **Phase-2b exit gate (parser):** a test runs `ParserAgent.parse_batch()` over mixed HTML/PDF fixtures for all 4 jurisdictions and asserts:
    - At least one `ParsedDocument` produced per fixture.
    - Each `ParsedDocument` has non-empty `body_text` (except scanned PDF), valid `doc_id`, `url`, `title`.
    - Metadata extraction yields expected `published_date`/`reference_number`/`document_type` for each jurisdiction's fixture.
    - No real network calls; no LLM/embedding provider imports.
- [ ] Fixtures committed under `tests/fixtures/parser/` (recorded once; no network in CI).
- [ ] `conftest.py` provides reusable `parser_agent` and `sample_raw_documents` fixtures.
- [ ] `src/regmon/parser/__init__.py` re-exports full public API so `from regmon.parser import HTMLParser, PDFParser, MetadataExtractor, ParserAgent, detect_content_type` works.
- [ ] No edits to `cli.py`, `scheduler.py`, `pipeline/`, `crawler/`, `normalize/`, `models/`, `db/`, `config/` (except `__init__.py` re-exports if needed) — surgical.
- [ ] `REGMON_DRY_RUN` not read; OSS-only deps confirmed (no `openai` import, no paid API calls).

---

**Branch:** `feature/parser-html-pdf`
**Spec file:** `.claude/specs/04-parser-html-pdf.md`
**Title:** Parser HTML/PDF
