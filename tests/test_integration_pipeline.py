"""Integration tests covering cross-phase pipeline flows."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from unittest.mock import call

import pytest

from events import EventType
from issue_store import IssueStoreStage
from models import IssueOutcomeType, QueueStats, ReviewVerdict, Task
from tests.conftest import (
    PlanResultFactory,
    ReviewResultFactory,
    TaskFactory,
    TriageResultFactory,
    WorkerResultFactory,
)
from tests.helpers import PipelineHarness


@dataclass
class PipelineRunResult:
    """Structured return data for a pipeline harness run."""

    task: Task
    triaged_count: int
    plan_results: list
    worker_results: list
    review_results: list
    snapshots: dict[str, QueueStats]

    def snapshot(self, label: str) -> QueueStats:
        return self.snapshots[label]


async def _run_happy_path(harness: PipelineHarness, task_id: int) -> PipelineRunResult:
    """Drive a single issue through triage → plan → implement → review."""
    task = TaskFactory.create(
        id=task_id,
        tags=[harness.config.find_label[0]],
    )
    harness.seed_issue(task, "find")

    harness.triage_runner.evaluate.return_value = TriageResultFactory.create(
        issue_number=task.id,
        ready=True,
    )
    harness.planners.plan.return_value = PlanResultFactory.create(
        issue_number=task.id,
    )

    branch = harness.config.branch_for_issue(task.id)
    worktree_path = harness.config.worktree_path_for_issue(task.id)
    harness.agents.run.return_value = WorkerResultFactory.create(
        issue_number=task.id,
        branch=branch,
        worktree_path=str(worktree_path),
        success=True,
        commits=1,
    )

    async def _review_side_effect(pr, issue, wt_path, diff, *, worker_id, **_kwargs):
        return ReviewResultFactory.create(
            pr_number=pr.number,
            issue_number=issue.id,
            verdict=ReviewVerdict.APPROVE,
            merged=True,
            ci_passed=True,
        )

    harness.reviewers.review.side_effect = _review_side_effect

    snapshots: dict[str, QueueStats] = {}

    def _capture(label: str) -> None:
        snapshots[label] = harness.store.get_queue_stats().model_copy(deep=True)

    triaged = await harness.triage_phase.triage_issues()
    _capture("after_triage")
    plan_results = await harness.plan_phase.plan_issues()
    _capture("after_plan")
    worker_results, _ = await harness.implement_phase.run_batch()
    _capture("after_implement")
    pr_info = worker_results[0].pr_info
    review_candidates = harness.store.get_reviewable(harness.config.batch_size)
    review_results = await harness.review_phase.review_prs([pr_info], review_candidates)
    _capture("after_review")

    # Allow async queue update events to flush.
    await asyncio.sleep(0)
    return PipelineRunResult(
        task=task,
        triaged_count=triaged,
        plan_results=plan_results,
        worker_results=worker_results,
        review_results=review_results,
        snapshots=snapshots,
    )


@pytest.mark.asyncio
async def test_pipeline_lifecycle_integration(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await _run_happy_path(harness, task_id=401)

    assert result.triaged_count == 1
    assert result.plan_results and result.plan_results[0].success
    assert result.worker_results and result.worker_results[0].success
    assert (
        result.review_results
        and result.review_results[0].verdict == ReviewVerdict.APPROVE
    )

    transition_calls = harness.prs.transition.await_args_list
    assert len(transition_calls) >= 3
    assert transition_calls[0] == call(result.task.id, "plan")
    assert transition_calls[1] == call(result.task.id, "ready")
    review_call = transition_calls[2]
    assert review_call.args[:2] == (result.task.id, "review")
    assert review_call.kwargs["pr_number"] == result.worker_results[0].pr_info.number


@pytest.mark.asyncio
async def test_plannable_data_flow_uses_issue_store_objects(tmp_path):
    harness = PipelineHarness(tmp_path)
    task = TaskFactory.create(
        id=777,
        tags=[harness.config.planner_label[0]],
    )
    harness.seed_issue(task, "plan")
    harness.planners.plan.return_value = PlanResultFactory.create(issue_number=task.id)

    await harness.plan_phase.plan_issues()

    called_issue = harness.planners.plan.await_args_list[0].args[0]
    assert called_issue is task


@pytest.mark.asyncio
async def test_event_bus_emits_ordered_phase_events(tmp_path):
    harness = PipelineHarness(tmp_path)
    await _run_happy_path(harness, task_id=502)

    events = harness.bus.get_history()
    queue_events = [e for e in events if e.type == EventType.QUEUE_UPDATE]
    assert len(queue_events) >= 4  # find, plan, ready, review transitions

    statuses = [
        e.data.get("status") for e in events if e.type == EventType.REVIEW_UPDATE
    ]
    assert statuses and statuses[0] == "start"
    assert "merging" in statuses


@pytest.mark.asyncio
async def test_post_merge_chain_updates_state_and_cleans_worktree(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await _run_happy_path(harness, task_id=903)

    outcome = harness.state.get_outcome(result.task.id)
    assert outcome is not None
    assert outcome.outcome == IssueOutcomeType.MERGED

    destroy_calls = harness.worktrees.destroy.await_args_list
    assert destroy_calls and destroy_calls[-1] == call(result.task.id)
    assert harness.state.get_active_worktrees() == {}

    events = harness.bus.get_history()
    assert any(
        e.type == EventType.REVIEW_UPDATE and e.data.get("status") == "merging"
        for e in events
    )


@pytest.mark.asyncio
async def test_enqueue_transition_handoff_updates_queue_depths(tmp_path):
    harness = PipelineHarness(tmp_path)
    result = await _run_happy_path(harness, task_id=1205)

    triage_stats = result.snapshot("after_triage")
    assert triage_stats.queue_depth[IssueStoreStage.PLAN] == 1
    assert triage_stats.queue_depth[IssueStoreStage.FIND] == 0

    plan_stats = result.snapshot("after_plan")
    assert plan_stats.queue_depth[IssueStoreStage.READY] == 1
    assert plan_stats.queue_depth[IssueStoreStage.PLAN] == 0

    implement_stats = result.snapshot("after_implement")
    assert implement_stats.queue_depth[IssueStoreStage.REVIEW] == 1
    assert implement_stats.queue_depth[IssueStoreStage.READY] == 0

    review_stats = result.snapshot("after_review")
    assert review_stats.queue_depth[IssueStoreStage.REVIEW] == 0
    assert review_stats.total_processed[IssueStoreStage.PLAN] >= 1
    assert review_stats.total_processed[IssueStoreStage.REVIEW] >= 1
