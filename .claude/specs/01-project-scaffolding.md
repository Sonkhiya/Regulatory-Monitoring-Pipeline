# Spec: Project Scaffolding

## Overview
This is **Phase 0** of plan.md §7 — the project bootstrap. It produces no pipeline logic: it lays down the `src/regmon` package skeleton (empty, importable modules per plan.md §8 layout, **plus a shared `llm/` provider layer mandated by the `create-spec` command**), the build/tooling configuration (`pyproject.toml` with OSS-only extras, `Makefile`, `.env.example`, `.gitignore`, pre-commit, CI), and the lint/format/type/test toolchain (ruff, black, mypy, pytest with an `integration` marker). It implements no pipeline stage (plan.md §2 graph stages remain unimplemented until Phases 1–6). It exists now because every subsequent phase depends on an importable package, a working `make lint`/`make test`, and a declared provider seam; without it, no module spec can be verified.

## Depends on
None — this is the first phase (plan.md §7 Phase 0). No prior modules or phases are prerequisites. It is the prerequisite for Phase 1 (Core data + persistence: `models/`, `db/`).

## Data models touched
None. Phase 0 creates no Pydantic models or enums. Enums (`Jurisdiction`, `PipelineStage`, `RunStatus`, etc.) and Pydantic models (`RegulatorySource`, `DocumentRecord`, `AuditEvent`, `RunContext`, etc. from plan.md §4.1/§4.2) land in Phase 1. Phase 0 only creates empty module packages.

## Database changes
No database changes. The `db/` package directory is created **empty** in Phase 0; the SQLAlchemy engine and the `documents`/`document_chunks`/`audit_log`/`pipeline_runs`/`run_memory`/`approvals`/`notifications` tables (plan.md §4.3) and `engine.py`/`document_store.py`/`audit_log.py` land in Phase 1. Phase 0 declares `REGMON_DB_URL` in `.env.example` but wires no engine.

## Module contract
- **Inputs:** none. Greenfield bootstrap driven by plan.md §8 layout + the `create-spec` command's provider directives. No runtime data flows in Phase 0.
- **Outputs:** an importable `regmon` package; a `regmon` console-script entry point (stub `main()`); `pyproject.toml`; `Makefile`; `.env.example`; `.gitignore`; `.pre-commit-config.yaml`; `.github/workflows/ci.yml`; tool configs (ruff/black/mypy/pytest in `pyproject.toml`); a smoke test proving importability.
- **Key functions/classes:** (Phase 0 stubs only — real implementations land in later phases)
  - `regmon/__init__.py` — package marker with `__version__`.
  - `regmon/__main__.py` — `python -m regmon` entry → delegates to `cli.main()`.
  - `regmon/cli.py` — `main() -> int` (argparse-based stub; prints version/exits 0; full `sources|run|backfill|status|approve` subcommands land in Phase 6).
  - `regmon/scheduler.py` — empty module (loop scheduler lands in Phase 6).
  - One empty `__init__.py` per subpackage: `config`, `models`, `crawler`, `parser`, `normalize`, `dedup`, `embeddings`, `rag`, `classification`, `summarization`, `risk`, `actions`, `approval`, `notifications`, `pipeline`, `db`, and the shared `llm` provider layer.
- **Edge cases:**
  - Missing optional extra at install time → core package still importable; provider extras (`faiss`/`chroma`/`local-llm`/`local-embeddings`) are guarded by later phases' import guards, not Phase 0.
  - Python < 3.10 → `pip install -e .` must refuse via `requires-python` (no runtime fallback).
  - `make lint`/`make test` run before `pip install -e ".[dev]"` → Makefile `install` target is the documented prerequisite; lint/test targets assume it (and CI installs first).
  - Empty subpackages under mypy → config must not error on empty modules.
  - CI on a fresh runner → workflow must `pip install -e ".[dev]"` before lint/test; cache pip wheels.

## Provider abstraction
Phase 0 scaffolding itself implements no providers — it is fully deterministic. But it establishes the **provider seam** that later phases populate, and the seam is **OSS-only** (per the `create-spec` command, overriding plan.md §5.1/§10 which named a hosted `openai` preset):

- **Shared layer:** `src/regmon/llm/` is created as the home for the shared LLM + embedding provider protocols. plan.md §8 does not list `llm/`; this spec **extends** the layout per the `create-spec` directive so that `classification/`, `summarization/`, `risk/`, and `embeddings/` never instantiate a provider client directly. The `llm/` package is **empty** in Phase 0; `EmbeddingProvider` protocol + `mock` + `sentence-transformers` impl land in Phase 3; `LLMProvider` protocol + `mock` + `ollama`/local-OpenAI-compatible impl land in Phase 4.
- **Module-local protocols (later phases):** `VectorStore` in `embeddings/` (`memory`/`faiss`/`chroma`); notification channels in `notifications/`.
- **`mock` provider:** remains the CI default in every phase that has providers; fully offline and deterministic. Phase 0 only declares the *keys*, not behavior.
- **Real backends (declared now, wired in Phase 7):** env vars select them — `REGMON_LLM_PROVIDER` ∈ {`mock`(default), `ollama`, `openai-local`} with `REGMON_LLM_BASE_URL` / `REGMON_LLM_MODEL`; `REGMON_EMBEDDING_PROVIDER` ∈ {`mock`(default), `sentence-transformers`} with `REGMON_EMBEDDING_MODEL`; `REGMON_VECTOR_STORE` ∈ {`memory`(default), `faiss`, `chroma`}.
- **No hosted-API-only provider** (`openai`-hosted, `anthropic`) is introduced as a hard dependency. A local OpenAI-compatible server reusing the `openai` *client SDK* against `base_url=http://localhost:...` is the only acceptable `openai`-client use.

## Audit & observability
Phase 0 emits no `AuditEvent`s and contributes no `RunContext` counts — nothing runs. The `PipelineStage` enum and `AuditEvent`/`RunContext` models land in Phase 1. Phase 0 only registers the pytest `integration` marker (in `pyproject.toml [tool.pytest.ini_options]`) that future audit-covered integration tests will use.

## Files to change
- `README.md` — expand the one-line stub to a minimal project header + quickstart (install / lint / test), consistent with plan.md §10/§11. Keep brief.
- `plan.md` — **proposed reconciliation (to be confirmed in Plan Mode):** update §8 layout to add `llm/`; update §5.1/§10 to replace the hosted `openai` preset with the OSS-only `ollama`/local-server + `sentence-transformers` presets and point LLM/embedding instantiation through `src/regmon/llm/`. Listed here so the canonical blueprint and the `create-spec` directive stay consistent; the change is deferred to Plan Mode sign-off since `plan.md` is canonical.

## Files to create
- `pyproject.toml` — project metadata, `requires-python>=3.10`, `console_scripts: regmon=regmon.cli:main`, core runtime deps (none required for the importable skeleton; provider deps live under extras), extras (`dev`, `faiss`, `chroma`, `local-llm`, `local-embeddings`), and `[tool.ruff]`, `[tool.black]`, `[tool.mypy]`, `[tool.pytest.ini_options]` (markers: `integration`; `asyncio_mode=auto`; `testpaths`).
- `Makefile` — targets: `install`, `lint`, `format`, `test`, `test-cov`, `hooks`, `clean` (per plan.md §10).
- `.env.example` — every `REGMON_*` var (`REGMON_DRY_RUN`, `REGMON_DB_URL`, `REGMON_LLM_PROVIDER`, `REGMON_LLM_BASE_URL`, `REGMON_LLM_MODEL`, `REGMON_EMBEDDING_PROVIDER`, `REGMON_EMBEDDING_MODEL`, `REGMON_VECTOR_STORE`, `REGMON_RISK_THRESHOLD`) + commented Slack/email placeholders; no real secrets.
- `.gitignore` — Python caches, `regmon.db`, `.env`, `dist/`, `build/`, `.coverage`, `.mypy_cache/`, `.pytest_cache/`, `.ruff_cache/`, `htmlcov/`, IDE dirs.
- `.pre-commit-config.yaml` — ruff, black, end-of-file-fixer, trailing-whitespace, check-yaml, mypy; `default_language_version: python3`.
- `.github/workflows/ci.yml` — matrix (Python 3.10/3.11/3.12/3.13): `pip install -e ".[dev]"`, `make lint`, `make test`; a separate `integration` job (manual or on tag) running `pytest -m integration` once those tests exist.
- `src/regmon/__init__.py` — `__version__ = "0.0.1"`, short docstring.
- `src/regmon/__main__.py` — `from regmon.cli import main; sys.exit(main())`.
- `src/regmon/cli.py` — `main() -> int` argparse stub (prints version, exits 0).
- `src/regmon/scheduler.py` — module docstring placeholder.
- `src/regmon/{config,models,crawler,parser,normalize,dedup,embeddings,rag,classification,summarization,risk,actions,approval,notifications,pipeline,db,llm}/__init__.py` — empty (one-line docstring each) placeholder packages.
- `tests/__init__.py`, `tests/test_smoke.py` — import `regmon` and every subpackage to prove the skeleton imports.

## New dependencies
- **`[dev]` extra:** `ruff`, `black`, `mypy`, `pytest`, `pytest-asyncio`, `pytest-cov`, `pre-commit`, `build`.
- **`[faiss]` extra (declared, wired in Phase 7):** `faiss-cpu`.
- **`[chroma]` extra (declared, wired in Phase 7):** `chromadb`.
- **`[local-llm]` extra (declared, wired in Phase 4/7):** `openai` (client SDK, pointed at a local `base_url`), optional `ollama`.
- **`[local-embeddings]` extra (declared, wired in Phase 3/7):** `sentence-transformers`.
- **Core runtime deps:** none pinned in Phase 0 (skeleton is empty-but-importable). `pydantic`, `pydantic-settings`, `sqlalchemy`, `httpx`, etc. are added by the phases that first need them.

## Rules for implementation
- Fully async where the module touches I/O — N/A for Phase 0 (no I/O). Forward-looking note: every later phase that adds `httpx`/DB/LLM calls must use `async def`.
- All external providers (LLM, embeddings, vector store) accessed through a protocol/interface — no provider is implemented in Phase 0, but the **seam** must exist: providers live in the shared `src/regmon/llm/` (LLM + embeddings) or module-local (`embeddings/VectorStore`, `notifications/` channels) layers, never instantiated inline in `classification/`/`summarization/`/`risk/`. Phase 0 creates the empty `llm/` package to enforce this structure.
- No secrets/API keys outside `config/Settings` — Phase 0 only declares keys in `.env.example`; no code reads them yet.
- All DB writes go through `src/regmon/db/` — N/A in Phase 0 (no DB writes).
- Audit log is append-only — N/A in Phase 0 (no audit).
- Deterministic behavior under `mock` providers — trivially satisfied in Phase 0 (no providers); the structure must keep `mock` the default.
- Type-hinted, passes `mypy` and `ruff` — Phase 0 stubs must have type hints where symbols are exported (`main() -> int`, `__version__: str`); `make lint` passes on the empty skeleton.
- Respects `REGMON_DRY_RUN` — N/A in Phase 0 (no outbound side effects).
- OSS-only: no hosted/paid LLM or embedding API is introduced. `openai` may appear only as the *client SDK* behind `[local-llm]`, talking to `base_url=http://localhost:...`.

## Testing plan
- **Unit tests:** `tests/test_smoke.py` imports `regmon` and every subpackage (`config`, `models`, `crawler`, `parser`, `normalize`, `dedup`, `embeddings`, `rag`, `classification`, `summarization`, `risk`, `actions`, `approval`, `notifications`, `pipeline`, `db`, `llm`) to assert the skeleton is importable. Also asserts `regmon.__version__` is a string and `regmon.cli.main()` (invoked directly or via a CliRunner/subprocess) returns `0`. Nothing is mocked in Phase 0 (no LLM/embeddings/http yet).
- **Integration test:** none in Phase 0. The `@pytest.mark.integration` marker is registered but unused; integration scenarios land with Phase 2+ (crawler fixtures) per plan.md §9.
- **Fixtures:** none created in Phase 0. `tests/fixtures/<jurisdiction>/` is created in Phase 2.

## Definition of done
- [ ] `pip install -e ".[dev]"` succeeds with no provider extras installed and the `regmon` package is importable.
- [ ] `make lint` passes (ruff + black --check + mypy) on the empty-but-importable skeleton.
- [ ] `make test` passes (`test_smoke.py` imports `regmon` + all 17 subpackages; `main()` exits 0).
- [ ] `python -m regmon` and `regmon` (console script) both run and exit 0.
- [ ] `make hooks` installs pre-commit; `pre-commit run --all-files` passes.
- [ ] `.env.example` exists and documents every `REGMON_*` var (no real secrets).
- [ ] `.github/workflows/ci.yml` exists and its lint+test job is green on Python 3.10–3.13.
- [ ] `pyproject.toml` declares extras `dev`, `faiss`, `chroma`, `local-llm`, `local-embeddings` (structure present; functional in Phases 3/4/7).
- [ ] (Recommended follow-up, Plan Mode sign-off) `plan.md` §5.1/§8/§10 reconciled with the OSS-only provider direction and the shared `llm/` layer.
