"""Smoke tests proving the Phase 0 skeleton is importable and runnable.

These tests assert that:
* ``regmon`` and every subpackage (17 total) imports cleanly.
* ``regmon.__version__`` is a non-empty string.
* ``regmon.cli.main([])`` returns 0 (direct call).
* ``python -m regmon`` exits 0 (subprocess).
* the ``regmon`` console script exits 0 when installed on PATH (subprocess).

Nothing is mocked in Phase 0 — there are no LLM/embeddings/http dependencies yet.
"""

from __future__ import annotations

import importlib
import shutil
import subprocess
import sys

import pytest

import regmon

SUBPACKAGES = [
    "config",
    "models",
    "crawler",
    "parser",
    "normalize",
    "dedup",
    "embeddings",
    "rag",
    "classification",
    "summarization",
    "risk",
    "actions",
    "approval",
    "notifications",
    "pipeline",
    "db",
    "llm",
]


@pytest.mark.parametrize("name", SUBPACKAGES)
def test_subpackage_importable(name: str) -> None:
    """Every Phase 0 subpackage must be importable from the installed package."""
    importlib.import_module(f"regmon.{name}")


def test_version_is_string() -> None:
    """``regmon.__version__`` must be a non-empty string."""
    assert isinstance(regmon.__version__, str)
    assert regmon.__version__


def test_main_returns_zero() -> None:
    """The console-script entry point returns 0 when invoked with no args."""
    from regmon.cli import main

    assert main([]) == 0


def test_python_m_regmon_exits_zero() -> None:
    """``python -m regmon`` runs and exits 0."""
    result = subprocess.run([sys.executable, "-m", "regmon"], check=False)
    assert result.returncode == 0


@pytest.mark.skipif(
    shutil.which("regmon") is None,
    reason="regmon console script not on PATH (run 'make install')",
)
def test_console_script_exits_zero() -> None:
    """The installed ``regmon`` console script runs and exits 0."""
    result = subprocess.run(["regmon"], check=False)
    assert result.returncode == 0
