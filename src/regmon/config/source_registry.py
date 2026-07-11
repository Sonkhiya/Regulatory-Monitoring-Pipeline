"""Source registry — loads ``sources.yaml`` into ``RegulatorySource`` objects (plan.md §5.1)."""

from __future__ import annotations

from pathlib import Path

import yaml

from regmon.models import Jurisdiction, RegulatorySource

DEFAULT_SOURCES_PATH = Path(__file__).with_name("sources.yaml")


def load_sources(path: Path | None = None) -> list[RegulatorySource]:
    """Load and validate regulatory sources from YAML.

    Args:
        path: Optional path to ``sources.yaml``. Defaults to the bundled file.

    Returns:
        A list of validated ``RegulatorySource`` objects.

    Raises:
        FileNotFoundError: If the YAML file does not exist.
        yaml.YAMLError: If the YAML is malformed.
        pydantic.ValidationError: If source entries don't match the schema.
    """
    src_path = path or DEFAULT_SOURCES_PATH
    if not src_path.exists():
        raise FileNotFoundError(f"Sources file not found: {src_path}")

    raw = yaml.safe_load(src_path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict) or "sources" not in raw:
        raise ValueError("YAML must contain a top-level 'sources' list")

    sources: list[RegulatorySource] = []
    for item in raw["sources"]:
        # Coerce jurisdiction string to enum
        if "jurisdiction" in item and isinstance(item["jurisdiction"], str):
            item["jurisdiction"] = Jurisdiction(item["jurisdiction"])
        sources.append(RegulatorySource(**item))
    return sources


class SourceRegistry:
    """Registry of configured regulatory sources with simple lookup helpers."""

    def __init__(self, sources: list[RegulatorySource] | None = None):
        self._sources = sources or load_sources()
        self._by_id = {s.id: s for s in self._sources}
        self._by_adapter: dict[str, list[RegulatorySource]] = {}
        for s in self._sources:
            self._by_adapter.setdefault(s.adapter, []).append(s)

    def __iter__(self):
        return iter(self._sources)

    def __len__(self) -> int:
        return len(self._sources)

    def get(self, source_id: str) -> RegulatorySource | None:
        """Get a source by its unique ID."""
        return self._by_id.get(source_id)

    def by_adapter(self, adapter: str) -> list[RegulatorySource]:
        """Get all sources using a given adapter."""
        return self._by_adapter.get(adapter, [])

    def by_jurisdiction(self, jurisdiction: Jurisdiction) -> list[RegulatorySource]:
        """Get all sources for a given jurisdiction."""
        return [s for s in self._sources if s.jurisdiction == jurisdiction]


# Module-level singleton (lazy-initialized on first access)
_registry: SourceRegistry | None = None


def get_source_registry() -> SourceRegistry:
    """Return the process-wide source registry singleton."""
    global _registry
    if _registry is None:
        _registry = SourceRegistry()
    return _registry
