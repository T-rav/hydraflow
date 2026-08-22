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
from models import PendingStageTransition, Task

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


class FakeTransitions:
    """The two ledger-backed intent slots, in memory."""

    def __init__(self) -> None:
        self.stage: dict[int, PendingStageTransition] = {}

    def record_stage_transition(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None:
        self.stage[issue_number] = PendingStageTransition(
            from_label=from_label,
            to_label=to_label,
            epoch=epoch,
            phase_attempt=phase_attempt,
        )

    def get_stage_transition(self, issue_number: int) -> PendingStageTransition | None:
        return self.stage.get(issue_number)

    def clear_stage_transition(self, issue_number: int) -> None:
        self.stage.pop(issue_number, None)


class StuckAdapter:
    """A plan adapter that never succeeds, so admitted drivers stay admitted."""

    phase = DriverPhase.PLAN
    target_label = PLAN_LABEL

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(ok=False, next_label=PLAN_LABEL, detail="still planning")


class MergingAdapter:
    """A plan adapter that takes the issue straight to a terminal state."""

    phase = DriverPhase.PLAN
    target_label = None

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
# Boot recovery admits at the reconciled stage, not the most advanced label
# --------------------------------------------------------------------------


class NoopAdapter:
    """An adapter that reports which phase was actually reached."""

    def __init__(self, phase: DriverPhase) -> None:
        self.phase = phase
        self.target_label = None

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(ok=False, next_label=lease.expected_stage_label, detail="x")


async def test_a_crashed_route_back_is_admitted_at_the_stage_its_intent_named(
    tmp_path: Path,
) -> None:
    # The case the whole C5(a) correction exists for, at the moment it matters
    # most. A DIAGNOSE -> READY route-back crashed mid-swap, so the issue
    # carries review(5) + ready(4). Admitting by most-advanced-wins would put a
    # driver on REVIEW and re-review an issue that was just sent back to be
    # re-implemented.
    task = Task(id=42, title="routed back", tags=[REVIEW_LABEL, READY_LABEL])
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        42, from_label=REVIEW_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    github = FakeGitHubLabels({42: [REVIEW_LABEL, READY_LABEL]})
    manager = DriverManager(
        store=FakeStore([task]),
        labels=PipelineLabelAdapter(
            github, ordered_labels=ORDERED_LABELS, transitions=transitions
        ),
        journal=DriverJournal(tmp_path / "driver_journal.jsonl"),
        ownership=DriverOwnershipRegistry(enabled=True),
        adapters={
            DriverPhase.PLAN: NoopAdapter(DriverPhase.PLAN),
            DriverPhase.IMPLEMENT: NoopAdapter(DriverPhase.IMPLEMENT),
            DriverPhase.REVIEW: NoopAdapter(DriverPhase.REVIEW),
        },
        stage_labels=STAGE_LABELS,
        repo_slug="acme/widgets",
        max_in_flight=4,
        stage_caps={},
    )

    await manager.tick()

    assert manager._drivers[42].driver_state == "READY"  # noqa: SLF001


async def test_a_consumed_intent_is_cleared_so_it_cannot_go_two_incarnations_stale(
    tmp_path: Path,
) -> None:
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        42, from_label=REVIEW_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    github = FakeGitHubLabels({42: [REVIEW_LABEL, READY_LABEL]})
    adapter = PipelineLabelAdapter(
        github, ordered_labels=ORDERED_LABELS, transitions=transitions
    )

    await adapter.reconcile(42, epoch=0, phase_attempt=0, consume=True)

    assert transitions.get_stage_transition(42) is None


async def test_a_live_boundary_read_does_not_consume_the_drivers_own_intent() -> None:
    # The record covers a swap that has not happened yet; clearing it on a read
    # would reopen the window it exists to close.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        42, from_label=PLAN_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    adapter = PipelineLabelAdapter(
        FakeGitHubLabels({42: [PLAN_LABEL]}),
        ordered_labels=ORDERED_LABELS,
        transitions=transitions,
    )

    await adapter.read_stage_label(42, epoch=0, phase_attempt=0)

    assert transitions.get_stage_transition(42) is not None


# --------------------------------------------------------------------------
# PipelineLabelAdapter — reconcile against recorded intent (ADR-0137 C5(a))
# --------------------------------------------------------------------------


def _adapter(
    labels: dict[int, list[str]], transitions: FakeTransitions | None = None
) -> PipelineLabelAdapter:
    return PipelineLabelAdapter(
        FakeGitHubLabels(labels),
        ordered_labels=ORDERED_LABELS,
        transitions=transitions,
    )


async def test_a_single_pipeline_label_is_the_truth() -> None:
    assert await _adapter({3: [READY_LABEL]}).read_stage_label(3) == READY_LABEL


async def test_an_issue_with_no_pipeline_label_reads_as_none() -> None:
    assert await _adapter({3: ["P1", "bug"]}).read_stage_label(3) is None


async def test_a_single_label_discards_a_stale_stage_intent() -> None:
    # A crash between the record and the label add leaves one label: the
    # transition never happened, and replaying its intent would invent one.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=PLAN_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    adapter = _adapter({3: [PLAN_LABEL]}, transitions)

    await adapter.reconcile(3, epoch=0, phase_attempt=0)

    assert transitions.get_stage_transition(3) is None


async def test_an_interrupted_route_back_completes_backwards_from_its_intent() -> None:
    # THE case priority-based reconciliation got wrong. DIAGNOSE -> READY
    # crashing mid-swap leaves review(5) + ready(4); most-advanced-wins picks
    # review and silently undoes the route-back.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=REVIEW_LABEL, to_label=READY_LABEL, epoch=1, phase_attempt=0
    )
    adapter = _adapter({3: [REVIEW_LABEL, READY_LABEL]}, transitions)

    resolved = await adapter.read_stage_label(3, epoch=1, phase_attempt=0)

    assert resolved == READY_LABEL


async def test_an_interrupted_hitl_resume_completes_backwards_from_its_intent() -> None:
    # The second backward edge: HITL(6) -> READY(4) reverts under priority.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=HITL_LABEL, to_label=READY_LABEL, epoch=2, phase_attempt=1
    )
    adapter = _adapter({3: [HITL_LABEL, READY_LABEL]}, transitions)

    resolved = await adapter.read_stage_label(3, epoch=2, phase_attempt=1)

    assert resolved == READY_LABEL


async def test_completing_an_interrupted_swap_removes_the_stale_from_label() -> None:
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=REVIEW_LABEL, to_label=READY_LABEL, epoch=1, phase_attempt=0
    )
    github = FakeGitHubLabels({3: [REVIEW_LABEL, READY_LABEL]})
    adapter = PipelineLabelAdapter(
        github, ordered_labels=ORDERED_LABELS, transitions=transitions
    )

    await adapter.reconcile(3, epoch=1, phase_attempt=0)

    assert github.labels[3] == [READY_LABEL]


async def test_an_intent_from_a_superseded_epoch_is_not_honoured() -> None:
    # Recovery honours the record written by the incarnation it replaces and
    # no older one; anything else falls through to the priority fallback.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=REVIEW_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    adapter = _adapter({3: [REVIEW_LABEL, READY_LABEL]}, transitions)

    resolved = await adapter.read_stage_label(3, epoch=5, phase_attempt=0)

    assert resolved == REVIEW_LABEL


async def test_a_label_outside_the_recorded_transition_is_adopted_not_clobbered() -> (
    None
):
    # An operator dragged the card during the swap window. ADR-0002 calls that
    # the escape hatch; the driver abandons its transition rather than
    # completing it over the top of the edit.
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=PLAN_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    adapter = _adapter({3: [PLAN_LABEL, READY_LABEL, HITL_LABEL]}, transitions)

    resolved = await adapter.read_stage_label(3, epoch=0, phase_attempt=0)

    assert resolved == HITL_LABEL


async def test_external_drift_never_removes_the_externally_set_label() -> None:
    transitions = FakeTransitions()
    transitions.record_stage_transition(
        3, from_label=PLAN_LABEL, to_label=READY_LABEL, epoch=0, phase_attempt=0
    )
    github = FakeGitHubLabels({3: [PLAN_LABEL, READY_LABEL, HITL_LABEL]})
    adapter = PipelineLabelAdapter(
        github, ordered_labels=ORDERED_LABELS, transitions=transitions
    )

    await adapter.reconcile(3, epoch=0, phase_attempt=0)

    assert github.swaps == []


async def test_two_labels_with_no_intent_fall_back_to_most_advanced() -> None:
    # Rule 4: unreachable via a driver crash (the record precedes the add), so
    # it exists for drift the driver did not cause — where forward-bias is
    # still the right guess.
    resolved = await _adapter({3: [PLAN_LABEL, READY_LABEL]}).read_stage_label(3)

    assert resolved == READY_LABEL


async def test_committing_a_stage_label_goes_through_the_existing_swap_primitive() -> (
    None
):
    github = FakeGitHubLabels({3: [PLAN_LABEL]})
    adapter = PipelineLabelAdapter(github, ordered_labels=ORDERED_LABELS)

    await adapter.commit_stage_label(3, READY_LABEL)

    assert github.swaps == [(3, READY_LABEL)]
