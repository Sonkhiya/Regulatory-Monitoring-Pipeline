"""regmon command-line interface (Phase 0 stub).

Full subcommands (``sources`` / ``run`` / ``backfill`` / ``status`` / ``approve``)
land in Phase 6. This stub exists so that ``regmon`` (console script) and
``python -m regmon`` both run and exit 0, proving the package is installed
correctly.
"""

from __future__ import annotations

import argparse

from regmon import __version__


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="regmon",
        description="Regulatory Monitoring Pipeline (Phase 0 stub).",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"regmon {__version__}",
    )
    return parser


def main(argv: list[str] | None = None) -> int:
    """Entry point for the ``regmon`` console script. Always exits 0 in Phase 0."""
    parser = _build_parser()
    parser.parse_args(argv)
    parser.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
