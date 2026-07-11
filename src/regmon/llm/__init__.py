"""Shared LLM and embedding provider protocols and backends (Phases 3/4+).

This is the only place where provider clients are instantiated. Other modules
(``classification``/``summarization``/``risk``/``embeddings``) consume the
protocols defined here and never construct a provider directly, which keeps the
``mock`` (offline, deterministic) default working at all times.
"""
