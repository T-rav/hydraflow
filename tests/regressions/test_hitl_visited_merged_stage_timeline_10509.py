"""Regression #10509: Work Stream stage timeline lied about merged issues.

The dashboard's per-issue stage timeline is fabricated client-side from a
single ``PipelineIssue`` snapshot entry — it has no per-stage history, only
the issue's *current* stage and status. Before this fix, ``IssueStore`` gave
the frontend no way to tell "never escalated" apart from "escalated, then
recovered" once an issue reached the terminal ``merged`` bucket: both looked
identical (no HITL evidence survived past the escalation).

Bug: ``_hitl_numbers`` is discarded the moment an issue leaves HITL (labels
move on), so by the time an issue merges, nothing on the wire distinguishes
it from one that never visited HITL at all. The frontend responded by
blanket-stamping every stage before the current pipeline position as "done"
(including hitl) — fabricating history for issues that never escalated.

Fix: ``IssueStore`` now tracks ``_hitl_visited`` — a durable, append-only
record of every issue number that has ever escalated to HITL — and stamps
``hitl_visited`` on ``PipelineSnapshotEntry``/``PipelineIssue`` so the
frontend can render "Needs Human" hollow (skipped) vs filled (visited and
recovered) based on real evidence instead of guessing from stage position.
Guards here also lock in that hitl/merged entries carry their real status
(``hitl``/``merged``), not a placeholder.
"""

from __future__ import annotations

from events import EventBus
from issue_store import STAGE_MERGED, IssueStore
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _make_store() -> IssueStore:
    from unittest.mock import AsyncMock

    config = ConfigFactory.create()
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    return IssueStore(config, fetcher, EventBus())


def test_merged_issue_that_never_escalated_has_no_hitl_history() -> None:
    store = _make_store()
    issue = TaskFactory.create(id=100, tags=["hydraflow-review"])
    store._route_issues([issue])
    store.mark_merged(100)

    snapshot = store.get_pipeline_snapshot()
    merged = next(e for e in snapshot[STAGE_MERGED] if e["issue_number"] == 100)

    assert merged["status"] == "merged"
    assert merged.get("hitl_visited") is False


def test_merged_issue_that_escalated_and_recovered_retains_hitl_history() -> None:
    store = _make_store()

    # Escalate to HITL...
    escalated = TaskFactory.create(id=101, tags=["hydraflow-hitl"])
    store._route_issues([escalated])
    assert 101 in store._hitl_numbers

    # ...a human resolves it, labels move the issue back into the pipeline...
    recovered = TaskFactory.create(id=101, tags=["hydraflow-review"])
    store._route_issues([recovered])
    assert 101 not in store._hitl_numbers  # current-HITL membership clears

    # ...and it eventually merges.
    store.mark_merged(101)

    snapshot = store.get_pipeline_snapshot()
    merged = next(e for e in snapshot[STAGE_MERGED] if e["issue_number"] == 101)

    assert merged["status"] == "merged"
    # The durable signal must survive even though _hitl_numbers cleared —
    # this is exactly what the frontend needs to render "Needs Human" filled
    # instead of hollow for an issue that genuinely visited and recovered.
    assert merged.get("hitl_visited") is True
