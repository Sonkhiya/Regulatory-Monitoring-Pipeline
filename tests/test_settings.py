"""Unit tests for :class:`Settings` / :func:`get_settings` (plan.md §5.1)."""

from __future__ import annotations

import os

import pytest

from regmon.config import Settings, get_settings
from regmon.config import settings as settings_module


@pytest.fixture
def clean_env(monkeypatch: pytest.MonkeyPatch) -> None:
    """Remove all ``REGMON_*`` env vars so ``Settings()`` defaults are observable."""
    for key in [k for k in os.environ if k.startswith("REGMON_")]:
        monkeypatch.delenv(key, raising=False)
    settings_module.get_settings.cache_clear()


def test_defaults_match_env_example(clean_env: None) -> None:
    """``Settings()`` defaults mirror ``.env.example``."""
    s = Settings()
    assert s.dry_run is True
    assert s.db_url == "sqlite+aiosqlite:///regmon.db"
    assert s.risk_threshold == 60
    assert s.llm_provider == "mock"
    assert s.embedding_provider == "mock"
    assert s.vector_store == "memory"
    assert s.llm_model == "llama3.1"
    assert s.smtp_port == 587


def test_env_override(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    """Explicit ``REGMON_*`` env vars override defaults."""
    monkeypatch.setenv("REGMON_DRY_RUN", "false")
    monkeypatch.setenv("REGMON_RISK_THRESHOLD", "42")
    monkeypatch.setenv("REGMON_LLM_PROVIDER", "ollama")
    s = Settings()
    assert s.dry_run is False
    assert s.risk_threshold == 42
    assert s.llm_provider == "ollama"


def test_extra_env_ignored(monkeypatch: pytest.MonkeyPatch, clean_env: None) -> None:
    """``extra="ignore"`` tolerates unrelated ``REGMON_*`` env vars."""
    monkeypatch.setenv("REGMON_TOTALLY_UNKNOWN", "whatever")
    Settings()  # must not raise


def test_get_settings_cached(clean_env: None) -> None:
    """``get_settings`` returns the same instance across calls."""
    settings_module.get_settings.cache_clear()
    a = get_settings()
    b = get_settings()
    assert a is b
