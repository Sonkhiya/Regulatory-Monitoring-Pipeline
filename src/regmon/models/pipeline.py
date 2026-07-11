"""Pipeline-control models: approval, notifications, audit, run state (plan.md §4.2).

``AuditEvent`` and ``RunContext`` are the cross-cutting vocabulary every later
stage writes to. ``AuditEvent`` is persisted to the append-only ``audit_log``
table; ``from_attributes`` lets ``AuditLog`` round-trip ORM rows. The approval
and notification models are Pydantic-only in Phase 1 (their tables arrive in
Phases 5-6).
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from pydantic import BaseModel, ConfigDict, Field

from regmon.models.enums import ApprovalDecision, PipelineStage, RunStatus
from regmon.models.results import ActionPlan, RiskAssessment


class ApprovalRequest(BaseModel):
    """A human-in-the-loop approval gate request for a high-risk document."""

    doc_id: str
    risk_assessment: RiskAssessment
    action_plan: ActionPlan
    requested_at: datetime
    decided_at: datetime | None = None
    decision: ApprovalDecision | None = None
    decision_by: str | None = None
    decision_note: str | None = None


class Notification(BaseModel):
    """An outbound notification over a channel (Slack/email), dedup-keyed."""

    channel: str
    recipient: str
    subject: str
    body: str
    doc_id: str
    sent_at: datetime
    dedup_key: str


class AuditEvent(BaseModel):
    """An append-only audit event for one pipeline stage of one run.

    ``ts`` is DB-defaulted to now on insert; it is ``None`` until persisted.
    Re-inserting the same ``event_id`` is rejected (duplicate PK) rather than
    overwriting — append-only integrity is enforced by ``AuditLog``.
    """

    model_config = ConfigDict(from_attributes=True)

    event_id: str
    ts: datetime | None = None
    stage: PipelineStage
    actor: str
    action: str
    doc_id: str | None = None
    run_id: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class RunContext(BaseModel):
    """Per-run orchestrator state: status, per-stage states, counts, errors."""

    run_id: str
    started_at: datetime
    ended_at: datetime | None = None
    status: RunStatus
    stage_states: dict[str, str] = Field(default_factory=dict)
    counts: dict[str, int] = Field(default_factory=dict)
    errors: list[str] = Field(default_factory=list)


__all__ = [
    "ApprovalRequest",
    "AuditEvent",
    "Notification",
    "RunContext",
]
