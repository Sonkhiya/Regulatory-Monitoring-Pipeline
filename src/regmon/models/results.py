"""Intelligence-stage result models (plan.md §4.2).

These are Pydantic-only in Phase 1 - defined now so the typed vocabulary is
complete, but their DB tables/persistence arrive in Phases 4-6. Phase 1 only
constructs and validates them in unit tests.
"""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, Field

from regmon.models.enums import RiskLevel, Urgency


class ClassificationResult(BaseModel):
    """Rule-/LLM-based classification of a ``NormalizedDocument``."""

    topics: list[str] = Field(default_factory=list)
    functions: list[str] = Field(default_factory=list)
    urgency: Urgency
    confidence: float
    rationale: str


class SummaryResult(BaseModel):
    """Structured summary of a document."""

    executive_summary: str
    key_points: list[str] = Field(default_factory=list)
    affected_business_areas: list[str] = Field(default_factory=list)
    compliance_implications: str


class RiskAssessment(BaseModel):
    """Weighted risk score + justifying drivers and RAG citations."""

    risk_level: RiskLevel
    score: int = Field(ge=0, le=100)
    drivers: list[str] = Field(default_factory=list)
    rag_citations: list[str] = Field(default_factory=list)


class ActionItem(BaseModel):
    """A single actionable task produced by the action planner."""

    action_id: str
    title: str
    description: str
    owner: str
    team: str
    priority: str
    due_date: datetime
    depends_on: list[str] = Field(default_factory=list)


class ActionPlan(BaseModel):
    """A plan of ``ActionItem``s for one document."""

    doc_id: str
    actions: list[ActionItem] = Field(default_factory=list)


__all__ = [
    "ActionItem",
    "ActionPlan",
    "ClassificationResult",
    "RiskAssessment",
    "SummaryResult",
]
