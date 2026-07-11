# Regulatory Monitoring Pipeline (`regmon`)

A multi-agent system that crawls regulatory sources (RBI, SEBI, FDA, EU AI Act),
parses and normalizes them, deduplicates across runs, classifies, summarizes, and
risk-assesses each document, then routes high-risk items through a
human-in-the-loop (HITL) approval gate before notifying via Slack/email — with
full append-only audit logging.

The pipeline runs **fully offline by default** using `mock` LLM and embedding
providers. Real backends are opt-in via OSS-only extras (local Ollama or a local
OpenAI-compatible server, sentence-transformers embeddings, FAISS/Chroma vector
stores). No hosted/paid LLM or embedding API is required.

## Quickstart

```bash
make install          # pip install -e ".[dev]"
make lint             # ruff + black --check + mypy
make test             # pytest (unit tests; integration is opt-in)
```

Run the CLI:

```bash
regmon --version      # or: python -m regmon
```

## Configuration

Copy `.env.example` to `.env` and adjust. Key settings:

| Variable | Default | Purpose |
|----------|---------|---------|
| `REGMON_DRY_RUN` | `true` | Suppress outbound notifications (log instead) |
| `REGMON_DB_URL` | `sqlite:///regmon.db` | SQLite or Postgres URL |
| `REGMON_LLM_PROVIDER` | `mock` | `mock` / `ollama` / `openai-local` |
| `REGMON_EMBEDDING_PROVIDER` | `mock` | `mock` / `sentence-transformers` |
| `REGMON_VECTOR_STORE` | `memory` | `memory` / `faiss` / `chroma` |
| `REGMON_RISK_THRESHOLD` | `60` | 0-100; at/above triggers HITL approval |

## Optional extras

```bash
pip install -e ".[faiss]"             # FAISS vector store
pip install -e ".[chroma]"            # Chroma vector store
pip install -e ".[local-llm]"         # local OpenAI-compatible LLM client
pip install -e ".[local-embeddings]"  # sentence-transformers embeddings
```

## Project layout

See `plan.md` for the canonical architecture, module contracts, and phased
build roadmap. Per-module implementation specs live under `.claude/specs/`.

## License

MIT
