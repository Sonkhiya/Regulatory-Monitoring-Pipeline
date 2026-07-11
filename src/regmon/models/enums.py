"""Enums for the Regulatory Monitoring Pipeline (plan.md §4.1).

All enums are ``str`` mixins so they serialise to their value string for
storage (e.g. database columns, JSON columns) and round-trip back to the
enum member via ``EnumType(value)``.
"""

from __future__ import annotations

from enum import Enum


class Jurisdiction(str, Enum):
    """Regulator jurisdictions monitored by the pipeline."""

    RBI = "RBI"
    SEBI = "SEBI"
    FDA = "FDA"
    EU_AI_ACT = "EU_AI_ACT"


class DocumentType(str, Enum):
    """Kinds of regulatory documents the pipeline can ingest."""

    NOTIFICATION = "NOTIFICATION"
    PRESS_RELEASE = "PRESS_RELEASE"
    CIRCULAR = "CIRCULAR"
    RSS_ITEM = "RSS_ITEM"
    REGULATION = "REGULATION"
    NEWS = "NEWS"


class Urgency(str, Enum):
    """How time-sensitive a document is, for classification escalation."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskLevel(str, Enum):
    """Risk-tier buckets derived from the 0-100 risk score."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class PipelineStage(str, Enum):
    """Stages the orchestrator progresses through; one per ``AuditEvent``."""

    CRAWL = "CRAWL"
    PARSE = "PARSE"
    NORMALIZE = "NORMALIZE"
    DEDUP = "DEDUP"
    CLASSIFY = "CLASSIFY"
    SUMMARIZE = "SUMMARIZE"
    INDEX = "INDEX"
    RISK = "RISK"
    PLAN = "PLAN"
    APPROVE = "APPROVE"
    NOTIFY = "NOTIFY"


class ApprovalDecision(str, Enum):
    """Outcomes of the human-in-the-loop approval gate."""

    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    DEFERRED = "DEFERRED"
    AUTO_APPROVED = "AUTO_APPROVED"


class RunStatus(str, Enum):
    """Lifecycle state of a pipeline run (``RunContext.status``)."""

    PENDING = "PENDING"
    RUNNING = "RUNNING"
    SUCCEEDED = "SUCCEEDED"
    FAILED = "FAILED"
    PARTIAL = "PARTIAL"


__all__ = [
    "ApprovalDecision",
    "DocumentType",
    "Jurisdiction",
    "PipelineStage",
    "RiskLevel",
    "RunStatus",
    "Urgency",
]
