---
description: Create a spec file and feature branch for the next Regulatory Monitoring Pipeline (regmon) module
argument-hint: "Step number and module name e.g. 3 dedup-engine"
allowed-tools: Read, Write, Glob, Bash(git:*)
---
You are a senior developer spinning up the next module of the
Regulatory Monitoring Pipeline (regmon). Always follow the rules
in `plan.md` (the canonical build blueprint).
User input: $ARGUMENTS

## Step 1 — Check working directory is clean
Run `git status` and check for uncommitted, unstaged, or
untracked files. If any exist, stop immediately and tell
the user to commit or stash changes before proceeding.
DO NOT CONTINUE until the working directory is clean.

## Step 2 — Parse the arguments
From $ARGUMENTS extract:
1. `step_number` — zero-padded to 2 digits: 3 → 03, 11 → 11
2. `module_title` — human readable title in Title Case
   - Example: "Deduplication Engine" or "Approval Gate"
3. `module_slug` — git and file safe slug
   - Lowercase, kebab-case
   - Only a-z, 0-9 and -
   - Maximum 40 characters
   - Example: dedup-engine, approval-gate
4. `branch_name` — format: `feature/<module_slug>`
   - Example: `feature/dedup-engine`
If you cannot infer these from $ARGUMENTS, ask the user
to clarify before proceeding.

## Step 3 — Check branch name is not taken
Run `git branch` to list existing branches.
If `branch_name` is already taken, append a number:
`feature/dedup-engine-01`, `feature/dedup-engine-02` etc.

## Step 4 — Switch to main and pull latest
Run:
```
git checkout main
git pull origin main
```

## Step 5 — Create and switch to the feature branch
Run:
```
git checkout -b <branch_name>
```

## Step 6 — Research the codebase
Read these before writing the spec:
- `plan.md` — canonical architecture, data flow, module contracts, phased roadmap
- `src/regmon/models/` — existing enums and Pydantic models
- `src/regmon/db/` — existing schema, engine, document_store, audit_log
- `src/regmon/config/` — Settings and source registry, provider presets
- `src/regmon/llm/` — shared LLM/embedding provider layer (protocol + `mock` +
  `ollama`/local-OpenAI-compatible backends). Any module needing an LLM or
  embeddings call MUST go through this shared layer — never instantiate a
  provider client directly inside `classification/`, `summarization/`, or `risk/`.
- The specific module directory under `src/regmon/<module>/` if it already partially exists
- All files in `.claude/specs/` — avoid duplicating or contradicting existing specs
- `tests/fixtures/` — check what recorded fixtures already exist for this module

Cross-check section 7 (Phased Build Roadmap) of `plan.md` to confirm:
- The requested module's phase prerequisites are already complete (e.g. don't spec Risk Assessment before Classification/Summarization exist)
- The module is not already marked complete in a prior spec
If a prerequisite is missing or the module is already done, warn the user and stop.

## Step 7 — Write the spec
Generate a spec document with this exact structure:

---
# Spec: <module_title>

## Overview
One paragraph describing what this module does, which pipeline
stage(s) it implements (see plan.md §2 Architecture & Data Flow),
and why it's needed at this point in the build roadmap.

## Depends on
Which previous modules/phases this requires to be complete
(reference plan.md §7 phase numbers and §5 module numbers).

## Data models touched
Which Pydantic models from plan.md §4.2 this module consumes
and/or produces (e.g. `NormalizedDocument` in → `DocumentRecord` out).
Note any new fields needed on existing models.

## Database changes
Any new tables, columns, or indexes needed in `src/regmon/db/`.
Always verify against the current schema before writing this.
If none: state "No database changes".

## Module contract
- **Inputs:** what this module receives and from where
- **Outputs:** what it returns/persists/emits
- **Key functions/classes:** names and signatures, matching the
  style of plan.md §5 (e.g. `ContentHasher.hash(text) -> str`)
- **Edge cases:** explicitly list failure modes and how they're handled

## Provider abstraction
This project is open-source-only: no hosted/paid LLM or embedding APIs.
If this module has swappable backends (LLM, embeddings, vector store,
notification channel), state:
- The protocol/interface name, and whether it lives in the shared
  `src/regmon/llm/` layer (LLM + embeddings) or is module-local
  (e.g. `VectorStore` in `embeddings/`, notification channels)
- The `mock` (offline, deterministic) implementation behavior — this
  remains the CI default regardless of which real backend exists
- The real backend(s) and which env var selects them, restricted to:
  - LLM: `ollama` or a local OpenAI-compatible server (vLLM, llama.cpp
    `server`, LM Studio) via `REGMON_LLM_PROVIDER` / `REGMON_LLM_BASE_URL` /
    `REGMON_LLM_MODEL`
  - Embeddings: `sentence-transformers` (e.g. `BAAI/bge-small-en-v1.5`) via
    `REGMON_EMBEDDING_PROVIDER` / `REGMON_EMBEDDING_MODEL`
  - Vector store: `memory` / `faiss` / `chroma` (already OSS, unchanged)
- Do NOT introduce a hosted-API-only provider (e.g. `openai`, `anthropic`)
  as a hard dependency. A local OpenAI-compatible server reusing the
  `openai` *client* SDK against `base_url=http://localhost:...` is
  acceptable since no external network call or paid key is involved.
If not applicable: state "No provider abstraction — deterministic module".

## Audit & observability
Which `AuditEvent`s this module must emit, and which `PipelineStage`
enum value(s) it corresponds to. Note any counts/errors this module
must contribute to `RunContext`.

## Files to change
Every file that will be modified.

## Files to create
Every new file that will be created.

## New dependencies
Any new pip packages, and which `pyproject.toml` extra (if any)
they belong under. If none: state "No new dependencies".

## Rules for implementation
Specific constraints Claude must follow. Always include:
- Fully async where the module touches I/O (`httpx`, DB, LLM calls)
- All external providers (LLM, embeddings, vector store) accessed
  through a protocol/interface — never called directly, so `mock`
  always works fully offline
- No secrets or API keys read outside `config/Settings`
- All DB writes go through `src/regmon/db/` — no raw SQL scattered
  in module code
- Audit log is append-only — never update or delete `AuditEvent` rows
- Deterministic behavior under `mock` providers (required for stable CI)
- Type-hinted, passes `mypy` and `ruff`
- Respects `REGMON_DRY_RUN` if this module can produce outbound side effects

## Testing plan
- **Unit tests:** what gets mocked (LLM/embeddings/http), which
  fixtures under `tests/fixtures/<jurisdiction>/` are needed or created
- **Integration test (if applicable):** what `@pytest.mark.integration`
  scenario this module needs, per plan.md §9

## Definition of done
A specific testable checklist. Each item must be verifiable by
running `make lint`, `make test`, or a specific `regmon` CLI command.
---

## Step 8 — Save the spec
Save to: `.claude/specs/<step_number>-<module_slug>.md`

## Step 9 — Report to the user
Print a short summary in this exact format:
```
Branch:    <branch_name>
Spec file: .claude/specs/<step_number>-<module_slug>.md
Title:     <module_title>
```
Then tell the user:
"Review the spec at `.claude/specs/<step_number>-<module_slug>.md`
then enter Plan Mode with Shift+Tab twice to begin implementation."

Do not print the full spec in chat unless explicitly asked.
