"""Unit tests for the Pydantic domain models and enums (plan.md §4.1/§4.2).

Pure construction + validation — no I/O, no mocking.
"""

from __future__ import annotations

from datetime import datetime

import pytest
from pydantic import ValidationError

import regmon.models as m

# ── Enums (plan.md §4.1) ────────────────────────────────────────────────────


@pytest.mark.parametrize(
    ("enum", "members"),
    [
        (m.Jurisdiction, ["RBI", "SEBI", "FDA", "EU_AI_ACT"]),
        (
            m.DocumentType,
            ["NOTIFICATION", "PRESS_RELEASE", "CIRCULAR", "RSS_ITEM", "REGULATION", "NEWS"],
        ),
        (m.Urgency, ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
        (m.RiskLevel, ["LOW", "MEDIUM", "HIGH", "CRITICAL"]),
        (
            m.PipelineStage,
            [
                "CRAWL",
                "PARSE",
                "NORMALIZE",
                "DEDUP",
                "CLASSIFY",
                "SUMMARIZE",
                "INDEX",
                "RISK",
                "PLAN",
                "APPROVE",
                "NOTIFY",
            ],
        ),
        (m.ApprovalDecision, ["APPROVED", "REJECTED", "DEFERRED", "AUTO_APPROVED"]),
        (m.RunStatus, ["PENDING", "RUNNING", "SUCCEEDED", "FAILED", "PARTIAL"]),
    ],
)
def test_enum_members(enum: type, members: list[str]) -> None:
    """Each enum exposes exactly the documented members with matching values."""
    assert {e.name for e in enum} == set(members)
    for name in members:
        assert enum[name].value == name


# ── Document chain ──────────────────────────────────────────────────────────


def test_regulatory_source_constructs() -> None:
    source = m.RegulatorySource(
        id="rbi-notifications",
        jurisdiction=m.Jurisdiction.RBI,
        name="RBI Notifications",
        listing_url="https://rbi.org.in/notifications",
        adapter="rbi",
    )
    assert source.feed_url is None
    assert source.crawl_policy == {}


def test_raw_document_constructs() -> None:
    doc = m.RawDocument(
        source_id="rbi",
        url="https://example.in/x",
        fetched_at=datetime(2026, 7, 11),
        http_status=200,
        content_bytes=b"hello",
    )
    assert doc.headers == {}
    assert doc.etag is None
    assert doc.last_modified is None


def test_parsed_document_optional_fields_default_none() -> None:
    doc = m.ParsedDocument(doc_id="d1", url="u", title="t", body_text="b")
    assert doc.published_date is None
    assert doc.reference_number is None
    assert doc.document_type is None
    assert doc.lang is None


def test_normalized_document_extends_parsed() -> None:
    norm = m.NormalizedDocument(
        doc_id="d1",
        url="u",
        title="t",
        body_text="b",
        clean_text="clean",
        language="en",
        char_count=5,
        word_count=1,
        document_type=m.DocumentType.CIRCULAR,
    )
    # Inherits ParsedDocument fields and adds its own.
    assert isinstance(norm, m.ParsedDocument)
    assert norm.clean_text == "clean"
    assert norm.document_type is m.DocumentType.CIRCULAR


def test_document_record_defaults() -> None:
    rec = m.DocumentRecord(
        doc_id="d1",
        source_id="rbi",
        url="u",
        title="t",
        body_text="b",
        clean_text="c",
        char_count=1,
        word_count=1,
        content_hash="deadbeef",
    )
    assert rec.simhash is None
    assert rec.embedding_ids == []
    assert rec.status == "new"
    assert rec.created_at is None
    assert rec.updated_at is None
    assert rec.jurisdiction is None


def test_document_chunk_constructs() -> None:
    chunk = m.DocumentChunk(chunk_id="c1", doc_id="d1", ord=0, text="hi", char_count=2)
    assert chunk.ord == 0


def test_document_record_rejects_missing_required() -> None:
    with pytest.raises(ValidationError):
        m.DocumentRecord(doc_id="d1")  # type: ignore[call-arg]


# ── Results ─────────────────────────────────────────────────────────────────


def test_classification_result_constructs() -> None:
    res = m.ClassificationResult(urgency=m.Urgency.HIGH, confidence=0.9, rationale="r")
    assert res.topics == []
    assert res.functions == []


def test_summary_result_requires_compliance_implications() -> None:
    with pytest.raises(ValidationError):
        m.SummaryResult(executive_summary="s", key_points=["a"])  # type: ignore[call-arg]


def test_risk_assessment_score_bounds() -> None:
    m.RiskAssessment(risk_level=m.RiskLevel.HIGH, score=75)
    with pytest.raises(ValidationError):
        m.RiskAssessment(risk_level=m.RiskLevel.HIGH, score=150)
    with pytest.raises(ValidationError):
        m.RiskAssessment(risk_level=m.RiskLevel.HIGH, score=-1)


def test_action_item_constructs() -> None:
    item = m.ActionItem(
        action_id="a1",
        title="t",
        description="d",
        owner="o",
        team="t",
        priority="P1",
        due_date=datetime(2026, 8, 1),
    )
    assert item.depends_on == []


def test_action_plan_constructs() -> None:
    plan = m.ActionPlan(doc_id="d1")
    assert plan.actions == []


# ── Pipeline control ───────────────────────────────────────────────────────


def test_approval_request_defaults_none() -> None:
    req = m.ApprovalRequest(
        doc_id="d1",
        risk_assessment=m.RiskAssessment(risk_level=m.RiskLevel.HIGH, score=70),
        action_plan=m.ActionPlan(doc_id="d1"),
        requested_at=datetime(2026, 7, 11),
    )
    assert req.decided_at is None
    assert req.decision is None


def test_notification_constructs() -> None:
    note = m.Notification(
        channel="slack",
        recipient="#alerts",
        subject="s",
        body="b",
        doc_id="d1",
        sent_at=datetime(2026, 7, 11),
        dedup_key="d1:review",
    )
    assert note.dedup_key == "d1:review"


def test_audit_event_defaults() -> None:
    ev = m.AuditEvent(
        event_id="e1",
        stage=m.PipelineStage.CRAWL,
        actor="crawler",
        action="fetched",
    )
    assert ev.ts is None
    assert ev.doc_id is None
    assert ev.run_id is None
    assert ev.metadata == {}


def test_run_context_defaults() -> None:
    ctx = m.RunContext(
        run_id="r1",
        started_at=datetime(2026, 7, 11),
        status=m.RunStatus.RUNNING,
    )
    assert ctx.ended_at is None
    assert ctx.stage_states == {}
    assert ctx.counts == {}
    assert ctx.errors == []
