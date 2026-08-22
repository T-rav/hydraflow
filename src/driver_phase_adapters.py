"""Explicit single-item adapters over the existing stage workers (#11535).

The proposal's P1 instruction is exact: *"Expose explicit single-item phase
adapters; do not call batch polling entry points from the driver."* Both halves
matter.

**Single-item**, because a batch entry point is a *scheduler*: ``plan_issues``
and ``run_batch()`` drain a queue, run a refilling pool and decide for themselves
how many issues to work. A driver that called one would be delegating the very
decision it exists to own, and two schedulers on one queue is the duplicate-
dispatch hazard the controller is supposed to remove. Each adapter here takes
exactly the one issue it was handed.

**Over the existing workers**, because #11535's acceptance criterion is that the
planner, implementer, reviewer and HITL contracts and output markers are
*preserved*. So no adapter reimplements a phase, rewrites a prompt, or parses a
transcript. Each one calls the same per-issue code path the Classic pool calls
and translates its existing result type into the driver's :class:`PhaseOutcome`.
If a prompt or a marker changes, it changes in one place, for both schedulers.

Triage is deliberately absent. An issue is not driver-owned until it has been
triaged — triage is intake, it decides whether the issue is workable at all, and
the driver admits issues that already carry a post-triage label. Adding a triage
adapter would extend driver ownership backwards over the one stage that decides
whether ownership is warranted. That stays Classic in P1.
"""

from __future__ import annotations

import asyncio
import logging
from typing import TYPE_CHECKING, Any, Protocol

from driver_contracts import DriverPhase
from issue_driver import PhaseOutcome

if TYPE_CHECKING:
    from driver_contracts import DriverLease
    from models import GitHubIssue, PlanResult, ReviewResult, Task, WorkerResult

logger = logging.getLogger("driver_phase_adapters")


class SingleItemPlanner(Protocol):
    """The planner's explicit single-item entry point."""

    async def plan_single_issue(
        self, issue: Task, *, semaphore: asyncio.Semaphore | None = None
    ) -> PlanResult: ...


class SingleItemImplementer(Protocol):
    """The implementer's existing explicit-list entry point, used with one item."""

    async def run_batch(
        self, issues: list[Task] | None = None
    ) -> tuple[list[WorkerResult], list[Task]]: ...


class SingleItemReviewer(Protocol):
    """The reviewer's existing entry point, used with one PR."""

    async def review_prs(
        self, prs: list[Any], issues: list[Task]
    ) -> list[ReviewResult]: ...


class ReviewablePRSource(Protocol):
    """Resolves the open PR for a review-stage issue."""

    async def fetch_reviewable_prs(
        self,
        active_issues: set[int],
        prefetched_issues: list[GitHubIssue] | None = None,
    ) -> tuple[list[Any], list[GitHubIssue]]: ...


class SingleItemHITLApplier(Protocol):
    """The HITL controller's explicit single-item entry point."""

    @property
    def hitl_corrections(self) -> dict[int, str]: ...

    async def process_single_correction(
        self, issue_number: int, correction: str
    ) -> None: ...


class PlanPhaseAdapter:
    """Plan one issue through ``PlanPhase``'s existing per-issue pipeline.

    The planner already swaps the issue to the ready label on success, so the
    driver's boundary usually observes the commit rather than issuing it; the
    nominal target is declared here so the boundary knows which label counts as
    coherent (see :func:`issue_driver_policy.admit_phase_result`).
    """

    phase = DriverPhase.PLAN

    def __init__(self, planner: SingleItemPlanner, *, ready_label: str) -> None:
        self._planner = planner
        self._ready_label = ready_label
        self.target_label: str | None = ready_label

    async def run(self, task: Task, *, lease: DriverLease) -> PhaseOutcome:
        result = await self._planner.plan_single_issue(task)
        if not result.success:
            return PhaseOutcome(
                ok=False,
                next_label=lease.expected_stage_label,
                detail=result.error or "plan failed",
            )
        return PhaseOutcome(
            ok=True,
            next_label=self._ready_label,
            artifact={
                "phase": self.phase.value,
                "issue": result.issue_number,
                "summary": result.summary,
                "actionability_rank": result.actionability_rank,
            },
            detail=result.summary,
        )


class ImplementPhaseAdapter:
    """Implement one issue through ``ImplementPhase``'s explicit-list mode.

    ``run_batch(issues=[task])`` is the documented "caller has done its own
    gating" path, so this uses the public contract as intended rather than
    reaching past it. The driver *is* the gate in controller mode — it admitted
    this issue and holds its lease.
    """

    phase = DriverPhase.IMPLEMENT

    def __init__(
        self, implementer: SingleItemImplementer, *, review_label: str
    ) -> None:
        self._implementer = implementer
        self._review_label = review_label
        self.target_label: str | None = review_label

    async def run(self, task: Task, *, lease: DriverLease) -> PhaseOutcome:
        results, _issues = await self._implementer.run_batch(issues=[task])
        result = next((r for r in results if r.issue_number == task.id), None)
        if result is None or not result.success:
            detail = (result.error if result else "no result") or "implement failed"
            return PhaseOutcome(
                ok=False, next_label=lease.expected_stage_label, detail=detail
            )
        return PhaseOutcome(
            ok=True,
            next_label=self._review_label,
            artifact={
                "phase": self.phase.value,
                "issue": result.issue_number,
                "branch": result.branch,
                "commits": result.commits,
                "pr": result.pr_info.number if result.pr_info else None,
            },
            detail=result.branch,
        )


class ReviewPhaseAdapter:
    """Review one issue's PR through ``ReviewPhase.review_prs`` with one PR.

    A review-stage issue whose PR is not visible yet is *not* a failure: the
    Classic path re-queues and waits, and so does this one — it reports a
    no-progress outcome and leaves the issue on the review label for the next
    tick, rather than burning a phase attempt on a propagation delay.
    """

    phase = DriverPhase.REVIEW

    def __init__(
        self,
        reviewer: SingleItemReviewer,
        fetcher: ReviewablePRSource,
        *,
        merged_state: str = "MERGED",
    ) -> None:
        self._reviewer = reviewer
        self._fetcher = fetcher
        self._merged_state = merged_state
        # Review declares no single target: it may merge (leaving the
        # pipeline), approve, or route back. The reviewer commits whichever
        # transition it decides on, and the driver follows the label.
        self.target_label: str | None = None

    async def run(self, task: Task, *, lease: DriverLease) -> PhaseOutcome:
        from models import GitHubIssue

        prs, issues = await self._fetcher.fetch_reviewable_prs(
            {task.id}, prefetched_issues=[GitHubIssue.from_task(task)]
        )
        if not prs:
            return PhaseOutcome(
                ok=False,
                next_label=lease.expected_stage_label,
                detail="pr not visible yet",
            )
        results = await self._reviewer.review_prs(
            prs[:1], [i.to_task() for i in issues[:1]] or [task]
        )
        result = next((r for r in results if r.issue_number == task.id), None)
        if result is None:
            return PhaseOutcome(
                ok=False,
                next_label=lease.expected_stage_label,
                detail="no review result",
            )
        artifact = {
            "phase": self.phase.value,
            "issue": result.issue_number,
            "pr": result.pr_number,
            "verdict": str(result.verdict),
            "merged": result.merged,
        }
        if result.merged:
            return PhaseOutcome(
                ok=True,
                next_label=None,
                next_state=self._merged_state,
                artifact=artifact,
                detail="merged",
            )
        # Not merged: the reviewer's own routing has already moved the label if
        # it decided to route back. The driver re-reads the label at the next
        # boundary and follows it, which is exactly ADR-0137 C5's rule.
        return PhaseOutcome(
            ok=False,
            next_label=lease.expected_stage_label,
            detail=result.summary or str(result.verdict),
        )


class HITLPhaseAdapter:
    """Apply one pending HITL correction through the existing HITL phase.

    ``HITL_WAIT`` is not this adapter's problem — a driver in that state is
    waiting on a human and has already released its slot (ADR-0137 C6). This
    runs only when a correction is actually pending, and reports no progress
    otherwise so the driver stays parked instead of spinning.
    """

    phase = DriverPhase.HITL

    def __init__(
        self, hitl: SingleItemHITLApplier, *, waiting_state: str = "HITL_WAIT"
    ) -> None:
        self._hitl = hitl
        self._waiting_state = waiting_state
        # A correction is applied in place; the stage label does not move.
        self.target_label: str | None = None

    async def run(self, task: Task, *, lease: DriverLease) -> PhaseOutcome:
        correction = self._hitl.hitl_corrections.get(task.id)
        if not correction:
            return PhaseOutcome(
                ok=False,
                next_label=lease.expected_stage_label,
                next_state=self._waiting_state,
                detail="awaiting operator correction",
            )
        await self._hitl.process_single_correction(task.id, correction)
        return PhaseOutcome(
            ok=True,
            next_label=lease.expected_stage_label,
            artifact={"phase": self.phase.value, "issue": task.id, "applied": True},
            detail="correction applied",
        )
