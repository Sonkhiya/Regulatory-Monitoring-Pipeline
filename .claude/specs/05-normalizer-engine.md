# Spec: Normalization Engine

## Overview
This is **Phase 2b (part)** of `plan.md §7` — the document normalization layer that sits between the parser (Phase 2a, spec `04-parser-html-pdf`) and the deduplication engine (Phase 3). It consumes `ParsedDocument` objects and produces `NormalizedDocument` objects with clean text, language tags, and token statistics. The module implements three core components: `EncodingRepair` (fixes mojibake/encoding issues via `ftfy` with `chardet` fallback), `BoilerplateStripper` (heuristic removal of repeated site chrome across crawl runs by tracking persistent n-grams), and `LanguageDetector` (`langdetect` primary with fast heuristic fallback). This module is fully deterministic, offline by default, and introduces no provider abstractions.

## Depends on
- **Phase 0 — Scaffolding (complete).** `pyproject.toml`, `Makefile`, ruff/black/mypy config, empty package skeleton.
- **Phase 1 — Core data + persistence (spec `02-data-models-persistence`, complete).** Provides `ParsedDocument`, `NormalizedDocument`, `Jurisdiction`, `DocumentType`, and `RegulatorySource` models.
- **Phase 2a — Crawler + adapters (spec `03-crawler-adapters`, complete).** Produces `RawDocument` objects from the four jurisdiction adapters.
- **Phase 2a — Parser (spec `04-parser-html-pdf`, complete).** Produces `ParsedDocument` with extracted `body_text`, `title`, and basic metadata.
- `plan.md §5.4` explicitly scopes `normalize/` within Phase 2 alongside `crawler/` and `parser/`.

## Data models touched
Consumes / produces models from `plan.md §4.2` (already defined in Phase 1):

- **Consumes:** `ParsedDocument` — `doc_id`, `url`, `title`, `body_text`, `published_date?`, `reference_number?`, `document_type?`, `lang?`.
- **Produces:** `NormalizedDocument` (extends `ParsedDocument`) — adds `clean_text`, `language`, `char_count`, `word_count`.
- **No new Pydantic models or enums** introduced by this module. The `NormalizedDocument` model already exists in `src/regmon/models/documents.py`.

## Database changes
**No database changes.** This module performs stateless text transformation only. It emits `NormalizedDocument` objects; the caller (pipeline orchestrator, Phase 6) persists them via `DocumentStore` (Phase 1) after deduplication (Phase 3). No new tables, columns, or indexes.

## Module contract
- **Inputs:**
  - `ParsedDocument` objects from `ParserAgent` (or test fixtures).
  - Optional jurisdiction hints for boilerplate n-gram tracking per-site.
- **Outputs:**
  - `NormalizedDocument` per successfully normalized `ParsedDocument`.
  - Normalization errors are logged; failed normalizations return `None` (caller decides to skip or record error).
- **Key functions/classes (signatures match `plan.md §5.4` style):**
  - `normalize/encoding_repair.py`:
    - `class EncodingRepair`
      - `__init__(enable_ftfy: bool = True, enable_chardet: bool = True)` — both enabled by default.
      - `repair(text: str) -> tuple[str, dict[str, Any]]` — returns `(clean_text, repair_info)` where `repair_info` contains `{"encoding_fixed": bool, "original_encoding": str | None, "ftfy_applied": bool}`. If input already clean, returns text unchanged.
  - `normalize/boilerplate.py`:
    - `class BoilerplateStripper`
      - `__init__(n_gram_size: int = 4, min_frequency: int = 3, min_length: int = 50)` — tracks n-grams seen across documents per jurisdiction/site to identify persistent boilerplate.
      - `strip(text: str, site_key: str = "default") -> tuple[str, dict[str, Any]]` — returns `(clean_text, strip_info)` with `strip_info` containing `{"boilerplate_removed": bool, "ngrams_stripped": list[str], "chars_removed": int}`. Updates internal n-gram frequency table for `site_key` (keyed by jurisdiction + domain).
      - `reset()` — clears learned n-gram frequencies (useful for tests).
  - `normalize/language.py`:
    - `class LanguageDetector`
      - `__init__(confidence_threshold: float = 0.5, fallback_lang: str = "en")` — `langdetect` used when available; heuristic (character script + common word checks) if not.
      - `detect(text: str) -> tuple[str, float]` — returns `(language_code, confidence)`. ISO 639-1 code (e.g., "en", "hi", "de", "fr"). Short text (< 20 chars) falls back to `fallback_lang` with confidence 0.1.
    - `function detect_language(text: str, confidence_threshold: float = 0.5) -> tuple[str, float]` — convenience function using default detector.
  - `normalize/__init__.py`:
    - `class NormalizerAgent` (orchestrator, mirrors `ParserAgent` style)
      - `__init__(encoding_repair?, boilerplate_stripper?, language_detector?, max_concurrent: int = 10)`
      - `async normalize(parsed_doc: ParsedDocument, site_key: str = "default") -> NormalizedDocument | None` — runs encoding repair → boilerplate strip → language detection → computes token stats.
      - `async normalize_batch(parsed_docs: list[ParsedDocument], site_keys: list[str]) -> tuple[list[NormalizedDocument], dict[str, Any]]` — concurrent with semaphore; returns stats: `normalized`, `failed`, `duration_seconds`, `errors`.
    - `def normalize_document(parsed_doc: ParsedDocument, site_key: str = "default") -> NormalizedDocument` — sync convenience for one-off use (uses default component instances).

- **Edge cases (explicit list):**
  - `ParsedDocument.body_text` empty or whitespace-only → `NormalizedDocument` with empty `clean_text`, `char_count=0`, `word_count=0`, `language` from detector fallback; log warning.
  - Encoding repair: input bytes not valid UTF-8 → decode with `errors="replace"` first, then `ftfy.fix_text` on resulting string; `repair_info["encoding_fixed"] = True`.
  - Boilerplate stripper: no persistent n-grams found (first run) → returns text unchanged, `strip_info["boilerplate_removed"] = False`.
  - Boilerplate stripper: text shorter than `min_length` → skip stripping, log DEBUG.
  - Language detection: `langdetect` raises `LangDetectException` on short/ambiguous text → catch, fall back to heuristic, then `fallback_lang`.
  - Language detection: text contains mixed scripts (e.g., English + Devanagari) → `langdetect` returns dominant language; heuristic checks script coverage.
  - Jurisdiction/site key for boilerplate tracking: derived from `ParsedDocument.url` domain + `Jurisdiction` if available, else "default".
  - Concurrent normalization limit respected via `asyncio.Semaphore` (default 10).

## Provider abstraction
**No provider abstraction — deterministic module.** All normalization uses OSS libraries (`ftfy`, `chardet`, `langdetect`). No LLM, embedding, or vector-store providers are invoked. `REGMON_LLM_PROVIDER` / `REGMON_EMBEDDING_PROVIDER` are not read here (consumed in Phases 3–7 only).

## Audit & observability
- **No `AuditEvent` emitted by this module.** The orchestrator (Phase 6) emits `PipelineStage.NORMALIZE` events when it wraps the normalizer. `NormalizerAgent` returns normalization stats (count, errors, duration) for the caller to include in `RunContext.counts` and `RunContext.errors`.
- **Logging:** `NormalizerAgent` uses `logging.getLogger(__name__)` at INFO for batch start/complete, WARNING for normalization failures (empty input, encoding issues), DEBUG for per-document steps (repair applied, boilerplate stripped, language detected).

## Files to change
- `pyproject.toml` — add **core runtime dep** `langdetect>=1.0` (ftfy and chardet already present from Phase 2a).
- `.env.example` — no new vars.
- `src/regmon/normalize/__init__.py` — re-export public API: `EncodingRepair`, `BoilerplateStripper`, `LanguageDetector`, `NormalizerAgent`, `normalize_document`, `detect_language`.

## Files to create
All new files (normalize package exists only as empty `__init__.py`):
- `src/regmon/normalize/encoding_repair.py` — `EncodingRepair` class
- `src/regmon/normalize/boilerplate.py` — `BoilerplateStripper` class
- `src/regmon/normalize/language.py` — `LanguageDetector` class + `detect_language` function
- `src/regmon/normalize/__init__.py` — `NormalizerAgent`, `normalize_document`, `detect_language`, re-exports
- `config/normalize_patterns.yaml` — optional config for boilerplate n-gram minimum frequency per jurisdiction (defaults in code if absent)
- `tests/fixtures/normalize/` — test fixtures:
  - `mojibake_utf8.txt` — UTF-8 text with common mojibake (e.g., "â€œ" for """, "Ã©" for "é")
  - `mojibake_latin1.txt` — Latin-1 misdecoded as UTF-8
  - `boilerplate_rbi.html` — RBI site with persistent nav/footer
  - `boilerplate_sebi.html` — SEBI site with persistent chrome
  - `short_text.txt` — < 20 chars for language detection fallback test
  - `mixed_lang.txt` — English + Hindi mixed content
- `tests/conftest.py` — add `normalizer_agent` fixture (instantiated `NormalizerAgent`), `sample_parsed_documents` fixture (list of `ParsedDocument` with varied content).
- `tests/test_normalize_encoding.py` — `EncodingRepair` unit tests: ftfy fixes mojibake, chardet fallback, clean text passthrough, empty input.
- `tests/test_normalize_boilerplate.py` — `BoilerplateStripper` unit tests: n-gram learning across calls, stripping repeated chrome, min_length threshold, reset().
- `tests/test_normalize_language.py` — `LanguageDetector` unit tests: langdetect primary path, heuristic fallback on exception, short text fallback, mixed script handling, confidence thresholds.
- `tests/test_normalize_agent.py` — `NormalizerAgent` orchestration: pipeline order (repair → strip → detect → stats), concurrent batch normalize, error handling, stats collection.

## New dependencies
- **Core runtime (added to `[project] dependencies` in `pyproject.toml`):** `langdetect>=1.0`
- **Already present (from Phase 2a parser spec):** `ftfy>=6.1`, `chardet` (transitive via ftfy), `pyyaml>=6.0`
- **No new optional extras.** All deps are OSS and required for normalizer to function.
- **Dev deps unchanged** (pytest/pytest-asyncio/pytest-cov/httpx already present).

## Rules for implementation
- **Fully async where I/O occurs** — `NormalizerAgent.normalize_batch` uses `asyncio.Semaphore` for concurrency; individual normalization steps are CPU-bound (run in thread pool via `asyncio.to_thread` if text > 100KB, else sync is fine). Encoder/boilerplate/language detectors can be sync; `NormalizerAgent` wraps in `to_thread` for large docs.
- **Provider protocol only for test injection** — `NormalizerAgent` accepts `encoding_repair`, `boilerplate_stripper`, `language_detector` as constructor args; tests can pass mocks.
- **No secrets/config outside `config/Settings`** — normalizer reads nothing from `os.environ`; optional pattern config loaded from `config/normalize_patterns.yaml` (bundled in package).
- **All DB writes through `src/regmon/db/`** — this module does **zero** DB writes; emits `NormalizedDocument` for orchestrator.
- **Audit log append-only** — not applicable here (no `AuditEvent` emission); Phase 6 owns that.
- **Deterministic behavior** — same input always produces same `NormalizedDocument`. Boilerplate stripper is stateful across calls (learns n-grams per site_key) but deterministic given same input sequence; `reset()` enables test isolation.
- **Type-hinted, passes `mypy` and `ruff`** — strict signatures; `ignored_missing_imports` for `langdetect`, `ftfy`, `bs4` in mypy config (already set for `bs4`).
- **Respects `REGMON_DRY_RUN`** — not applicable (no outbound side effects).

## Testing plan
- **Unit tests (no `@pytest.mark.integration`):**
  - `test_normalize_encoding.py`:
    - `EncodingRepair.repair` on `mojibake_utf8.txt` → clean ASCII/UTF-8, `repair_info["ftfy_applied"] = True`.
    - `EncodingRepair.repair` on `mojibake_latin1.txt` → clean text, encoding detection works.
    - Clean English text → returned unchanged, `repair_info["ftfy_applied"] = False`.
    - Empty string → returned unchanged, `encoding_fixed = False`.
  - `test_normalize_boilerplate.py`:
    - First call with RBI-like text → no stripping (learning phase).
    - Second call with same boilerplate + different body → boilerplate n-grams stripped, `strip_info["boilerplate_removed"] = True`.
    - Text shorter than `min_length` → no stripping, log DEBUG.
    - `reset()` clears learned n-grams; subsequent call treats as first.
    - Different `site_key` tracks separate n-gram tables.
  - `test_normalize_language.py` (parameterized):
    - English text → `("en", confidence > 0.9)`.
    - Hindi (Devanagari) text → `("hi", confidence > 0.5)` via heuristic if langdetect unavailable.
    - Short text (< 20 chars) → `(fallback_lang, 0.1)`.
    - Mixed English + Hindi → dominant script language detected.
    - `LangDetectException` caught → heuristic fallback used.
  - `test_normalize_agent.py`:
    - `NormalizerAgent.normalize` runs repair → strip → detect → stats in order.
    - `NormalizedDocument` has all fields: `clean_text`, `language`, `char_count`, `word_count` plus inherited `ParsedDocument` fields.
    - `normalize_batch` with semaphore=2 processes 5 docs, max 2 concurrent.
    - Failed normalization (empty body) returns `None`, logs warning, other docs succeed.
    - Stats returned: `normalized`, `failed`, `duration_seconds`, `errors`.
- **Fixtures under `tests/fixtures/normalize/`:**
  - Text files as listed above.
  - Re-use some parser fixtures for boilerplate testing (e.g., `rbi_notification.html` contains nav/footer chrome).
- **Integration test:** Not in this spec (Phase 2 exit says "offline tests with fixtures"); full pipeline integration with crawler+parser+normalize is Phase 2 end-to-end but not a separate `@pytest.mark.integration` here.

## Definition of done
- [ ] `pip install -e ".[dev]"` succeeds; new dep `langdetect` installed.
- [ ] `make lint` passes (ruff + black `--check` + mypy) on new `normalize/` code.
- [ ] `make test` passes — all new unit tests green, existing Phase 0/1/2a/2b (parser) tests still green.
- [ ] **Phase-2b exit gate (normalize):** a test runs `NormalizerAgent.normalize_batch()` over mixed `ParsedDocument` fixtures (including mojibake, boilerplate-heavy, multi-language) and asserts:
    - At least one `NormalizedDocument` produced per fixture.
    - Each `NormalizedDocument` has non-empty `clean_text` (except empty-input case), valid `language` code, `char_count > 0`, `word_count > 0`.
    - Encoding repair fixes known mojibake patterns in fixtures.
    - Boilerplate stripper removes repeated n-grams on second+ call for same `site_key`.
    - Language detection yields ISO 639-1 codes for each fixture's primary language.
    - No real network calls; no LLM/embedding provider imports.
- [ ] Fixtures committed under `tests/fixtures/normalize/`.
- [ ] `conftest.py` provides reusable `normalizer_agent` and `sample_parsed_documents` fixtures.
- [ ] `src/regmon/normalize/__init__.py` re-exports full public API so `from regmon.normalize import EncodingRepair, BoilerplateStripper, LanguageDetector, NormalizerAgent, normalize_document, detect_language` works.
- [ ] No edits to `cli.py`, `scheduler.py`, `pipeline/`, `crawler/`, `parser/`, `models/`, `db/`, `config/` (except `__init__.py` re-exports if needed) — surgical.
- [ ] `REGMON_DRY_RUN` not read; OSS-only deps confirmed (no `openai` import, no paid API calls).

---

**Branch:** `feature/normalizer-engine`
**Spec file:** `.claude/specs/05-normalizer-engine.md`
**Title:** Normalization Engine
