"""Unit tests for :class:`AuditLog` — Phase-1 exit gate B.

Append + list round-trip; assert append-only API (no update/delete).
"""

from __future__ import annotations

from datetime import datetime

import pytest

from regmon.db.audit_log import AuditLog
from regmon.models.enums import PipelineStage
from regmon.models.pipeline import AuditEvent


def make_event(event_id: str, run_id: str = "run-1") -> AuditEvent:
    return AuditEvent(
        event_id=event_id,
        ts=datetime(2026, 7, 11, 10, 0, 0),
        stage=PipelineStage.CRAWL,
        actor="crawler",
        action="fetched",
        run_id=run_id,
        doc_id="doc-1",
    )


async def test_append_and_list_round_trip(sessions) -> None:
    """Append an event and list it back ordered by ts ascending."""
    log = AuditLog(sessions)
    await log.append(make_event("e-1"))
    await log.append(make_event("e-2", run_id="run-2"))

    events = await log.list()
    assert [e.event_id for e in events] == ["e-1", "e-2"]
    assert all(e.ts is not None for e in events)
    assert events[0].ts <= events[1].ts


async def test_list_filters_by_run_id(sessions) -> None:
    log = AuditLog(sessions)
    await log.append(make_event("e-1", run_id="run-1"))
    await log.append(make_event("e-2", run_id="run-2"))

    run1 = await log.list(run_id="run-1")
    assert [e.event_id for e in run1] == ["e-1"]


async def test_list_filters_by_stage(sessions) -> None:
    log = AuditLog(sessions)
    await log.append(make_event("e-1"))  # CRAWL
    await log.append(
        AuditEvent(
            event_id="e-2",
            stage=PipelineStage.PARSE,
            actor="parser",
            action="parsed",
        )
    )

    crawl = await log.list(stage=PipelineStage.CRAWL)
    assert [e.event_id for e in crawl] == ["e-1"]


async def test_duplicate_event_id_raises(sessions) -> None:
    """Re-inserting the same event_id raises (duplicate PK)."""
    log = AuditLog(sessions)
    await log.append(make_event("dup"))
    with pytest.raises(ValueError, match="duplicate event_id"):
        await log.append(make_event("dup"))


async def test_auditlog_api_append_only(sessions) -> None:
    """``AuditLog`` exposes no public update/delete/remove method."""
    log = AuditLog(sessions)
    assert not hasattr(log, "update")
    assert not hasattr(log, "delete")
    assert not hasattr(log, "remove")


async def test_list_limit(sessions) -> None:
    log = AuditLog(sessions)
    await log.append(make_event("e-1"))
    await log.append(make_event("e-2"))
    await log.append(make_event("e-3"))

    assert len(await log.list(limit=2)) == 2
    assert len(await log.list(limit=100)) == 3
