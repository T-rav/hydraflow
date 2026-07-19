"""Regression: review-labeled issues with no agent PR sat idle forever (#9815).

A factory restart mid-implement leaves an issue on ``hydraflow-review`` with
no open ``agent/issue-N`` PR. The review loop found no PR and re-enqueued the
issue to review eternally (live example: #9553, attempts exhausted, no PR,
never picked again).

Pinned contract for ``_handle_review_orphan``: strikes below the threshold
keep the legacy propagation wait; at the threshold the issue is requeued to
ready with fresh attempt budget; requeues are bounded and then escalate to
HITL; gh failures and the ``max_requeues=0`` kill-switch fall back to legacy
behavior.
"""

from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import pytest

from models import Task
from orchestrator import HydraFlowOrchestrator


def _issue(n: int = 42) -> Task:
    return Task(
        id=n,
        title="Stuck after restart",
        body="x" * 60,
        tags=[],
        comments=[],
        source_url="",
        links=[],
        complexity_score=0,
        created_at="",
        metadata={},
    )


def _orch(state, *, threshold: int = 3, max_requeues: int = 3):
    config = MagicMock()
    config.review_orphan_strike_threshold = threshold
    config.review_orphan_max_requeues = max_requeues
    config.ready_label = ["hydraflow-ready"]
    config.hitl_label = ["hydraflow-hitl"]
    prs = MagicMock()
    prs.swap_pipeline_labels = AsyncMock()
    prs.post_comment = AsyncMock()
    return (
        SimpleNamespace(_config=config, _state=state, _svc=SimpleNamespace(prs=prs)),
        prs,
    )


@pytest.mark.asyncio
async def test_below_threshold_keeps_legacy_wait(state) -> None:
    orch, prs = _orch(state)

    handled = await HydraFlowOrchestrator._handle_review_orphan(orch, _issue())

    assert handled is False
    prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_threshold_strike_requeues_to_ready_with_fresh_budget(state) -> None:
    orch, prs = _orch(state)
    issue = _issue()
    state.increment_issue_attempts(issue.id)
    state.increment_issue_attempts(issue.id)

    handled = False
    for _ in range(3):
        handled = await HydraFlowOrchestrator._handle_review_orphan(orch, issue)

    assert handled is True
    prs.swap_pipeline_labels.assert_awaited_once_with(issue.id, "hydraflow-ready")
    prs.post_comment.assert_awaited_once()
    assert state.get_issue_attempts(issue.id) == 0  # fresh budget
    assert state.get_review_orphan_requeues(issue.id) == 1
    # Strikes reset — the next PR-less sighting starts a new streak.
    assert state.increment_review_orphan_strike(issue.id) == 1


@pytest.mark.asyncio
async def test_exhausted_requeues_escalate_to_hitl(state) -> None:
    orch, prs = _orch(state, max_requeues=1)
    issue = _issue()
    for _ in range(3):  # first orphan round -> requeue 1/1
        await HydraFlowOrchestrator._handle_review_orphan(orch, issue)
    prs.swap_pipeline_labels.reset_mock()
    prs.post_comment.reset_mock()

    handled = False
    for _ in range(3):  # second orphan round exceeds the bound
        handled = await HydraFlowOrchestrator._handle_review_orphan(orch, issue)

    assert handled is True
    prs.swap_pipeline_labels.assert_awaited_once_with(issue.id, "hydraflow-hitl")
    assert "needs a human" in (state.get_hitl_cause(issue.id) or "")


@pytest.mark.asyncio
async def test_zero_max_requeues_disables_feature(state) -> None:
    orch, prs = _orch(state, max_requeues=0)

    for _ in range(10):
        assert (
            await HydraFlowOrchestrator._handle_review_orphan(orch, _issue()) is False
        )
    prs.swap_pipeline_labels.assert_not_awaited()


@pytest.mark.asyncio
async def test_gh_failure_falls_back_to_legacy_wait(state) -> None:
    orch, prs = _orch(state)
    prs.swap_pipeline_labels = AsyncMock(side_effect=RuntimeError("gh down"))
    issue = _issue()

    handled = True
    for _ in range(3):
        handled = await HydraFlowOrchestrator._handle_review_orphan(orch, issue)

    assert handled is False  # caller keeps the legacy review wait
