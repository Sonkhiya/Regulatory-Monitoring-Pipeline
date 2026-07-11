"""Application settings loaded from environment / ``.env`` (plan.md §5.1).

Single source of truth for all ``REGMON_*`` configuration — no secret or
config value is read outside this module. Field names map to
``REGMON_<FIELD>`` env vars; all defaults mirror ``.env.example``.

In Phase 1 only ``db_url``, ``dry_run``, and ``risk_threshold`` are consumed;
the provider/notification fields are declared-but-unwired (consumed in
Phases 3-7). None is a hosted/paid API -- ``openai`` stays an optional client
SDK behind the ``local-llm`` extra, pointed at localhost.
"""

from __future__ import annotations

from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Environment-driven configuration for the regmon pipeline.

    ``extra="ignore"`` tolerates unrelated ``REGMON_*`` env vars so partial
    configs don't error.
    """

    model_config = SettingsConfigDict(
        env_prefix="REGMON_",
        env_file=".env",
        extra="ignore",
    )

    # ── General ───────────────────────────────────────────────────────────
    dry_run: bool = True

    # ── Database ──────────────────────────────────────────────────────────
    db_url: str = "sqlite+aiosqlite:///regmon.db"

    # --- LLM provider (OSS-only; consumed in Phases 3-7) ---------------------------
    llm_provider: str = "mock"
    llm_base_url: str = "http://localhost:11434/v1"
    llm_model: str = "llama3.1"

    # --- Embedding provider (OSS-only; consumed in Phases 3-7) --------------------
    embedding_provider: str = "mock"
    embedding_model: str = "BAAI/bge-small-en-v1.5"

    # ── Vector store ──────────────────────────────────────────────────────
    vector_store: str = "memory"

    # ── Risk ──────────────────────────────────────────────────────────────
    risk_threshold: int = 60

    # ── Notifications (optional; empty disables the channel) ────────────
    slack_webhook_url: str = ""
    smtp_host: str = ""
    smtp_port: int = 587
    smtp_username: str = ""
    smtp_password: str = ""
    email_from: str = "regmon-alerts@example.com"
    email_to: str = ""


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Return the process-wide cached :class:`Settings` instance."""
    return Settings()
