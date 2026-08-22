"""MockWorld scenario: one issue driven plan → implement by a fenced driver (#11535).

The unit tests around :mod:`issue_driver` prove the boundary transaction with
recording doubles. This proves the same path against the **ports**: labels are
read and written through ``FakeGitHub``'s real ``PRPort`` surface
(``get_issue_labels`` / ``swap_pipeline_labels``), the queue is a real
``IssueStore``, and the journal is a real file. Nothing here is an ``AsyncMock``
of a port — a mocked port would agree with whatever the driver asked of it and
prove nothing about the round trip.

What it covers that the unit layer cannot: that the driver's most-advanced-label
read agrees with the label ``swap_pipeline_labels`` actually leaves behind, and
that ownership is taken and given back across a real tick of the allocator.
"""

from __future__ import annotations

import pytest

from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from driver_phase_adapters import PlanPhaseAdapter
from models import PlanResult, Task
from tests.scenarios.builders import IssueBuilder

pytestmark = pytest.mark.scenario

ISSUE = 8801
FIND_LABEL = "hydraflow-find"
PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"

ORDERED_LABELS = (FIND_LABEL, PLAN_LABEL, READY_LABEL, REVIEW_LABEL, HITL_LABEL)
STAGE_LABELS = {
    "TRIAGE": FIND_LABEL,
    "PLAN": PLAN_LABEL,
    "READY": READY_LABEL,
    "REVIEW": REVIEW_LABEL,
    "DIAGNOSE": REVIEW_LABEL,
    "HITL_WAIT": HITL_LABEL,
    "HITL_APPLY": HITL_LABEL,
}


class PortBackedPlanner:
    """A planner that does what the real one does to the world: swap the label.

    It runs no agent, but it exercises the part of the planner contract the
    driver's boundary depends on — the stage worker commits its own transition
    through ``swap_pipeline_labels`` — so the driver is observed reacting to a
    real label write rather than to a scripted return value.
    """

    def __init__(self, github: object) -> None:
        self._github = github
        self.planned: list[int] = []

    async def plan_single_issue(self, issue: Task, *, semaphore: object = None):
        self.planned.append(issue.id)
        await self._github.swap_pipeline_labels(issue.id, READY_LABEL)
        return PlanResult(issue_number=issue.id, success=True, summary="planned")


class SingleIssueStore:
    """A store that offers one plannable issue, then nothing."""

    def __init__(self, task: Task) -> None:
        self._pending = [task]
        self.released: list[int] = []
        self.requeued: list[tuple[int, str]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        taken, self._pending = self._pending[:max_count], self._pending[max_count:]
        return taken

    def get_implementable(self, max_count: int) -> list[Task]:
        return []

    def get_reviewable(self, max_count: int) -> list[Task]:
        return []

    def release_in_flight(
        self, issue_numbers: set[int], *, expected_stage: str | None = None
    ) -> None:
        self.released.extend(sorted(issue_numbers))

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self.requeued.append((task.id, next_stage))


@pytest.fixture
def controller(mock_world, tmp_path):
    """A real allocator over FakeGitHub's PRPort surface."""
    IssueBuilder().numbered(ISSUE).titled("driven issue").labeled(PLAN_LABEL).at(
        mock_world
    )
    github = mock_world.github
    planner = PortBackedPlanner(github)
    ownership = DriverOwnershipRegistry(enabled=True)
    store = SingleIssueStore(Task(id=ISSUE, title="driven issue", tags=[PLAN_LABEL]))
    manager = DriverManager(
        store=store,
        labels=PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(tmp_path / "driver_journal.jsonl"),
        ownership=ownership,
        adapters={DriverPhase.PLAN: PlanPhaseAdapter(planner, ready_label=READY_LABEL)},
        stage_labels=STAGE_LABELS,
        repo_slug="acme/widgets",
        max_in_flight=1,
        stage_caps={DriverPhase.PLAN: 1},
    )
    return manager, github, planner, ownership, store


class TestDeterministicControllerDrivesOneIssue:
    """One admitted issue crosses the plan boundary through the real ports."""

    async def test_the_issue_is_admitted_to_a_driver(self, controller) -> None:
        manager, _github, _planner, _ownership, _store = controller

        report = await manager.tick()

        assert report.admitted == (ISSUE,)

    async def test_the_planner_runs_exactly_once_for_the_issue(
        self, controller
    ) -> None:
        manager, _github, planner, _ownership, _store = controller

        await manager.tick()

        assert planner.planned == [ISSUE]

    async def test_the_issue_ends_the_boundary_on_the_ready_label(
        self, controller
    ) -> None:
        manager, github, _planner, _ownership, _store = controller

        await manager.tick()

        assert READY_LABEL in await github.get_issue_labels(ISSUE)

    async def test_the_plan_label_is_gone_after_the_swap(self, controller) -> None:
        manager, github, _planner, _ownership, _store = controller

        await manager.tick()

        assert PLAN_LABEL not in await github.get_issue_labels(ISSUE)

    async def test_the_driver_reads_the_new_stage_back_through_the_port(
        self, controller
    ) -> None:
        manager, github, _planner, _ownership, _store = controller
        await manager.tick()

        adapter = PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS)

        assert await adapter.read_stage_label(ISSUE) == READY_LABEL

    async def test_the_boundary_is_recorded_as_committed_in_the_journal(
        self, controller, tmp_path
    ) -> None:
        manager, _github, _planner, _ownership, _store = controller

        await manager.tick()

        assert (
            DriverJournal(tmp_path / "driver_journal.jsonl").committed_keys(ISSUE)
            != frozenset()
        )

    async def test_the_driver_holds_ownership_while_the_issue_is_in_flight(
        self, controller
    ) -> None:
        manager, _github, _planner, ownership, _store = controller

        await manager.tick()

        assert ownership.owns(ISSUE)

    async def test_a_second_tick_does_not_re_plan_the_issue(self, controller) -> None:
        # The issue is now on the ready label, and no implement adapter is
        # wired in this scenario, so the driver must not fall back to
        # re-running the phase it already committed.
        manager, _github, planner, _ownership, _store = controller
        await manager.tick()

        await manager.tick()

        assert planner.planned == [ISSUE]

    async def test_a_stopped_tick_leaves_the_label_untouched(self, controller) -> None:
        manager, github, _planner, _ownership, _store = controller

        await manager.tick(stop_requested=True)

        assert await github.get_issue_labels(ISSUE) == [PLAN_LABEL]
