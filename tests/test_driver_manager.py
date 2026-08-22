"""Unit tests for the ``issue_controller`` capacity allocator (#11535).

The allocator's four jobs — admit, release, recover, fence on stop — are what is
asserted here. Phases are scripted; what matters is who got a slot, who gave one
back, and what happened after a stop.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from issue_driver import PhaseOutcome
from models import Task

if TYPE_CHECKING:
    from pathlib import Path

PLAN_LABEL = "hydraflow-plan"
READY_LABEL = "hydraflow-ready"
REVIEW_LABEL = "hydraflow-review"
HITL_LABEL = "hydraflow-hitl"
FIND_LABEL = "hydraflow-find"

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


class FakeGitHubLabels:
    """Minimal ``PRPort`` surface: the issue label set, readable and swappable."""

    def __init__(self, labels: dict[int, list[str]]) -> None:
        self.labels = labels
        self.swaps: list[tuple[int, str]] = []

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        return list(self.labels.get(issue_number, []))

    async def swap_pipeline_labels(
        self, issue_number: int, new_label: str, *, pr_number: int | None = None
    ) -> None:
        self.swaps.append((issue_number, new_label))
        self.labels[issue_number] = [new_label]


class FakeStore:
    """Just the four ``IssueStorePort`` methods the allocator uses."""

    def __init__(self, plannable: list[Task] | None = None) -> None:
        self._plannable = list(plannable or [])
        self.released: list[int] = []
        self.requeued: list[tuple[int, str]] = []

    def get_plannable(self, max_count: int) -> list[Task]:
        taken, self._plannable = (
            self._plannable[:max_count],
            self._plannable[max_count:],
        )
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


class StuckAdapter:
    """A plan adapter that never succeeds, so admitted drivers stay admitted."""

    phase = DriverPhase.PLAN

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(ok=False, next_label=PLAN_LABEL, detail="still planning")


class MergingAdapter:
    """A plan adapter that takes the issue straight to a terminal state."""

    phase = DriverPhase.PLAN

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(ok=True, next_label=None, next_state="MERGED", artifact={})


def _plan_task(number: int) -> Task:
    return Task(id=number, title=f"issue {number}", tags=[PLAN_LABEL])


def _manager(
    tmp_path: Path,
    *,
    tasks: list[Task],
    adapter: object | None = None,
    max_in_flight: int = 2,
    stage_caps: dict[DriverPhase, int] | None = None,
    ownership: DriverOwnershipRegistry | None = None,
    github: FakeGitHubLabels | None = None,
    store: FakeStore | None = None,
) -> DriverManager:
    gh = github or FakeGitHubLabels({t.id: [PLAN_LABEL] for t in tasks})
    return DriverManager(
        store=store or FakeStore(tasks),
        labels=PipelineLabelAdapter(gh, ordered_labels=ORDERED_LABELS),
        journal=DriverJournal(tmp_path / "driver_journal.jsonl"),
        ownership=ownership or DriverOwnershipRegistry(enabled=True),
        adapters={DriverPhase.PLAN: adapter or StuckAdapter()},
        stage_labels=STAGE_LABELS,
        repo_slug="acme/widgets",
        max_in_flight=max_in_flight,
        stage_caps=stage_caps or {DriverPhase.PLAN: 4},
    )


# --------------------------------------------------------------------------
# Admission and the global WIP cap
# --------------------------------------------------------------------------


async def test_a_plannable_issue_is_admitted_to_a_driver(tmp_path: Path) -> None:
    manager = _manager(tmp_path, tasks=[_plan_task(1)])

    report = await manager.tick()

    assert report.admitted == (1,)


async def test_admission_stops_at_the_global_wip_cap(tmp_path: Path) -> None:
    manager = _manager(
        tmp_path, tasks=[_plan_task(1), _plan_task(2), _plan_task(3)], max_in_flight=2
    )

    report = await manager.tick()

    assert len(report.admitted) == 2


async def test_admission_respects_the_existing_per_stage_worker_cap(
    tmp_path: Path,
) -> None:
    # ADR-0137 C4: the allocator respects ``max_planners`` rather than
    # replacing it, so a global cap of 3 still admits only one planner.
    manager = _manager(
        tmp_path,
        tasks=[_plan_task(1), _plan_task(2), _plan_task(3)],
        max_in_flight=3,
        stage_caps={DriverPhase.PLAN: 1},
    )

    report = await manager.tick()

    assert len(report.admitted) == 1


async def test_a_candidate_declined_by_a_stage_cap_goes_back_on_its_queue(
    tmp_path: Path,
) -> None:
    # ``get_plannable`` splices the task out of its deque and stamps it
    # in-flight, so a declined candidate that is merely dropped would not
    # reappear until the next full GitHub poll — a silent per-issue delay of a
    # whole poll interval caused by the very cap that is meant to be free.
    # Global capacity is 3, so three are pulled; the plan cap of 1 declines two.
    store = FakeStore([_plan_task(1), _plan_task(2), _plan_task(3)])
    manager = _manager(
        tmp_path,
        tasks=[_plan_task(1), _plan_task(2), _plan_task(3)],
        max_in_flight=3,
        stage_caps={DriverPhase.PLAN: 1},
        store=store,
    )

    await manager.tick()

    assert store.requeued == [(2, "plan"), (3, "plan")]


async def test_an_admitted_issue_is_not_put_back_on_its_queue(tmp_path: Path) -> None:
    store = FakeStore([_plan_task(1)])
    manager = _manager(tmp_path, tasks=[_plan_task(1)], store=store)

    await manager.tick()

    assert store.requeued == []


async def test_an_admitted_issue_is_claimed_in_the_ownership_registry(
    tmp_path: Path,
) -> None:
    ownership = DriverOwnershipRegistry(enabled=True)
    manager = _manager(tmp_path, tasks=[_plan_task(7)], ownership=ownership)

    await manager.tick()

    assert ownership.owns(7)


async def test_an_issue_owned_by_another_driver_is_not_admitted_twice(
    tmp_path: Path,
) -> None:
    ownership = DriverOwnershipRegistry(enabled=True)
    ownership.claim(7, driver_id="someone-else", epoch=0)
    manager = _manager(tmp_path, tasks=[_plan_task(7)], ownership=ownership)

    report = await manager.tick()

    assert report.admitted == ()


# --------------------------------------------------------------------------
# Retirement and release
# --------------------------------------------------------------------------


async def test_a_retired_driver_gives_its_ownership_claim_back(tmp_path: Path) -> None:
    ownership = DriverOwnershipRegistry(enabled=True)
    manager = _manager(
        tmp_path, tasks=[_plan_task(9)], adapter=MergingAdapter(), ownership=ownership
    )
    await manager.tick()

    await manager.tick()

    assert not ownership.owns(9)


async def test_a_retired_driver_releases_its_store_claim(tmp_path: Path) -> None:
    store = FakeStore([_plan_task(9)])
    manager = _manager(
        tmp_path, tasks=[_plan_task(9)], adapter=MergingAdapter(), store=store
    )
    await manager.tick()

    await manager.tick()

    assert 9 in store.released


async def test_release_all_drops_every_claim(tmp_path: Path) -> None:
    ownership = DriverOwnershipRegistry(enabled=True)
    manager = _manager(tmp_path, tasks=[_plan_task(1)], ownership=ownership)
    await manager.tick()

    manager.release_all()

    assert manager.driven_issues == frozenset()


# --------------------------------------------------------------------------
# C6 — non-working drivers release their slot
# --------------------------------------------------------------------------


async def test_a_parked_driver_does_not_occupy_a_wip_slot(tmp_path: Path) -> None:
    manager = _manager(tmp_path, tasks=[_plan_task(1)], max_in_flight=1)
    await manager.tick()
    driver = next(iter(manager._drivers.values()))  # noqa: SLF001
    driver.adopt_live_state("PARKED")

    assert manager.occupancy().in_flight == 0


# --------------------------------------------------------------------------
# The stop fence
# --------------------------------------------------------------------------


async def test_a_stopped_tick_admits_nothing(tmp_path: Path) -> None:
    manager = _manager(tmp_path, tasks=[_plan_task(1)])

    report = await manager.tick(stop_requested=True)

    assert report.admitted == ()


async def test_a_stopped_tick_reports_that_it_was_fenced(tmp_path: Path) -> None:
    manager = _manager(tmp_path, tasks=[_plan_task(1)])

    report = await manager.tick(stop_requested=True)

    assert report.stopped is True


# --------------------------------------------------------------------------
# Recovery — the epoch survives a restart
# --------------------------------------------------------------------------


async def test_a_driver_rebuilt_after_a_restart_takes_a_higher_epoch(
    tmp_path: Path,
) -> None:
    # A previous process committed a boundary at epoch 4; a driver rebuilt for
    # the same issue must fence that generation rather than reuse its token.
    from driver_contracts import DriverCheckpoint

    journal = DriverJournal(tmp_path / "driver_journal.jsonl")
    journal.append_checkpoint(
        11,
        "11:4:PLAN:0",
        DriverCheckpoint(
            driver_id="drv-old",
            epoch=4,
            last_committed_phase=DriverPhase.PLAN,
            committed_stage_label=READY_LABEL,
            capsule_digest="deadbeef",
        ),
    )
    manager = _manager(tmp_path, tasks=[_plan_task(11)])

    await manager.tick()

    assert next(iter(manager._drivers.values())).epoch == 5  # noqa: SLF001


# --------------------------------------------------------------------------
# PipelineLabelAdapter — most-advanced-label-wins
# --------------------------------------------------------------------------


async def test_a_mid_swap_crash_leaving_two_labels_resolves_to_the_newer_stage() -> (
    None
):
    # ``swap_pipeline_labels`` adds the forward label before removing the old
    # one, so a crash between the two leaves both. ADR-0137 C5a: reuse
    # IssueStore's most-advanced-wins rule, which biases correctly forward.
    github = FakeGitHubLabels({3: [PLAN_LABEL, READY_LABEL]})
    adapter = PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS)

    assert await adapter.read_stage_label(3) == READY_LABEL


async def test_an_issue_with_no_pipeline_label_reads_as_none() -> None:
    github = FakeGitHubLabels({3: ["P1", "bug"]})
    adapter = PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS)

    assert await adapter.read_stage_label(3) is None


async def test_committing_a_stage_label_goes_through_the_existing_swap_primitive() -> (
    None
):
    github = FakeGitHubLabels({3: [PLAN_LABEL]})
    adapter = PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS)

    await adapter.commit_stage_label(3, READY_LABEL)

    assert github.swaps == [(3, READY_LABEL)]
