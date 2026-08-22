"""The idle tick that spun the allocator and fsync'd a row per iteration.

#11537 shipped a shadow observer that correctly declined to run a Fable turn on
an idle tick — and then wrote a durable, fsync'd row saying so. Its own comment
justified that as costing "one row per poll interval". The premise was false.

``DriverTickReport.did_work`` counted an ``IDLE`` advance as work, and
``_polling_loop`` skips its sleep whenever a tick did work. So a single PARKED
or HITL_WAIT driver drove the allocator at loop speed, not at ``poll_interval``
— harmless for as long as the wasted work was a dict lookup, and a disk-write
firehose the moment an observer hung off it. The aggregate spend ceiling then
made it worse rather than better: once the ceiling bit, every one of those
iterations also emitted a warning and rebuilt a summary dict.

Three separate things had to be true for that to happen, so there are three
groups here. The first is the cause and is fixed in the driver, where every
future consumer of the tick benefits. The second and third are the defence in
depth in the observer, so that a future re-introduction of a busy tick cannot
turn into disk I/O again.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from director_shadow_log import ShadowObservationLog, TurnFailure
from driver_contracts import DriverPhase
from driver_journal import DriverJournal
from driver_manager import DriverManager, DriverTickReport, PipelineLabelAdapter
from driver_ownership import DriverOwnershipRegistry
from issue_driver import AdvanceOutcome, DriverAdvance, PhaseOutcome
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
    "HITL_WAIT": HITL_LABEL,
}


def _advance(outcome: AdvanceOutcome) -> DriverAdvance:
    return DriverAdvance(
        issue_number=1,
        driver_id="drv-1",
        epoch=0,
        phase=None if outcome is AdvanceOutcome.IDLE else DriverPhase.PLAN,
        outcome=outcome,
        state="PARKED" if outcome is AdvanceOutcome.IDLE else "PLAN",
    )


class TestAnIdleAdvanceIsNotWork:
    """The cause. Fixed in the driver, so every consumer of the tick benefits."""

    def test_a_tick_whose_only_advance_was_idle_did_no_work(self) -> None:
        # This is the whole bug in one line: True here means _polling_loop
        # takes `if did_work: continue` and never sleeps.
        report = DriverTickReport(advanced=(_advance(AdvanceOutcome.IDLE),))

        assert report.did_work is False

    def test_a_committed_advance_is_still_work(self) -> None:
        report = DriverTickReport(advanced=(_advance(AdvanceOutcome.COMMITTED),))

        assert report.did_work is True

    def test_one_real_advance_among_idle_ones_is_still_work(self) -> None:
        report = DriverTickReport(
            advanced=(
                _advance(AdvanceOutcome.IDLE),
                _advance(AdvanceOutcome.COMMITTED),
            )
        )

        assert report.did_work is True

    def test_an_admission_is_work_even_with_nothing_advanced(self) -> None:
        assert DriverTickReport(admitted=(1,)).did_work is True

    def test_a_release_is_work_even_with_nothing_advanced(self) -> None:
        assert DriverTickReport(released=(1,)).did_work is True

    def test_an_empty_tick_did_no_work(self) -> None:
        assert DriverTickReport().did_work is False


class SpinningObserver:
    """Counts how many times the allocator offered it a boundary."""

    def __init__(self) -> None:
        self.offers = 0

    async def observe_boundary(self, *, task, advance, driver) -> None:
        self.offers += 1


class ParkedAdapter:
    """A phase that leaves the driver with nothing further to run."""

    phase = DriverPhase.PLAN
    target_label = None
    sub_state_target = None

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(ok=True, next_label=None, next_state="PARKED", artifact={})


class FakeGitHubLabels:
    def __init__(self, labels: dict[int, list[str]]) -> None:
        self.labels = labels

    async def get_issue_labels(self, issue_number: int) -> list[str]:
        return list(self.labels.get(issue_number, []))

    async def swap_pipeline_labels(
        self, issue_number: int, new_label: str, *, pr_number: int | None = None
    ) -> None:
        self.labels[issue_number] = [new_label]


class FakeStore:
    def __init__(self, tasks: list[Task]) -> None:
        self._pending = list(tasks)

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
        return None

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        return None


class TestAParkedDriverStopsEarningImmediateRePolls:
    """The cause, end to end through a real allocator tick."""

    async def _manager(self, tmp_path: Path, observer: object) -> DriverManager:
        task = Task(id=1, title="parked issue", tags=[PLAN_LABEL])
        return DriverManager(
            store=FakeStore([task]),
            labels=PipelineLabelAdapter(
                FakeGitHubLabels({1: [PLAN_LABEL]}), ordered_labels=ORDERED_LABELS
            ),
            journal=DriverJournal(tmp_path / "journal.jsonl"),
            ownership=DriverOwnershipRegistry(enabled=True),
            adapters={DriverPhase.PLAN: ParkedAdapter()},
            stage_labels=STAGE_LABELS,
            repo_slug="acme/widgets",
            max_in_flight=2,
            stage_caps={DriverPhase.PLAN: 2},
            observer=observer,
        )

    async def test_the_tick_after_a_driver_parks_reports_no_work(
        self, tmp_path: Path
    ) -> None:
        manager = await self._manager(tmp_path, SpinningObserver())
        await manager.tick()

        report = await manager.tick()

        assert report.did_work is False

    async def test_the_parked_driver_is_still_ticked(self, tmp_path: Path) -> None:
        # Releasing a slot must not mean going dormant — a HITL driver has to
        # keep being asked so it notices the operator's answer. The fix bounds
        # the RATE, it does not stop the ticking.
        observer = SpinningObserver()
        manager = await self._manager(tmp_path, observer)
        await manager.tick()

        await manager.tick()

        assert observer.offers == 2


class WaitingOnAHumanAdapter:
    """The HITL phase's real no-correction shape: a barrier, not an attempt."""

    phase = DriverPhase.HITL
    target_label = None
    sub_state_target = None

    async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
        return PhaseOutcome(
            ok=False,
            next_label=HITL_LABEL,
            next_state="HITL_WAIT",
            detail="awaiting operator correction",
            no_progress=True,
        )


class TestABarrierIsNotAFailedAttempt:
    """The half of the spin that ``IDLE`` alone did not cover.

    A PARKED driver reports ``IDLE``, so excluding ``IDLE`` from ``did_work``
    fixes it. A driver waiting on a *human* does not: the HITL adapter's
    no-correction path returned ``ok=False``, which the driver read as a failed
    attempt. So the loop still never slept for the one state that waits longest,
    the attempt counter climbed once per tick for as long as the operator took to
    answer — and that counter keys the boundary idempotency key — and a shadow
    director bought a turn on every one of those ticks.

    ``ReviewPhaseAdapter`` has documented this exact intent since #11535 ("rather
    than burning a phase attempt on a propagation delay") without a field to
    express it.
    """

    async def _driver(self, tmp_path: Path):
        from issue_driver import IssueDriver

        class Labels:
            async def read_stage_label(
                self, n: int, *, epoch: int = 0, phase_attempt: int = 0
            ) -> str:
                return HITL_LABEL

            def record_intent(self, *a: object, **k: object) -> None: ...
            def clear_intent(self, *a: object, **k: object) -> None: ...
            async def commit_stage_label(self, *a: object, **k: object) -> None: ...

        return IssueDriver(
            issue_number=1,
            driver_id="drv-1",
            repo_slug="acme/widgets",
            adapters={DriverPhase.HITL: WaitingOnAHumanAdapter()},
            labels=Labels(),
            journal=DriverJournal(tmp_path / "journal.jsonl"),
            stage_labels={"HITL_WAIT": HITL_LABEL, "HITL_APPLY": HITL_LABEL},
            driver_state="HITL_WAIT",
        )

    async def test_waiting_on_a_human_reports_idle_not_failed(
        self, tmp_path: Path
    ) -> None:
        driver = await self._driver(tmp_path)

        advance = await driver.advance(Task(id=1, title="escalated", tags=[]))

        assert advance.outcome is AdvanceOutcome.IDLE

    async def test_waiting_on_a_human_burns_no_phase_attempt(
        self, tmp_path: Path
    ) -> None:
        # The counter keys the boundary idempotency key, so an unbounded climb
        # while nothing is wrong is not merely cosmetic.
        driver = await self._driver(tmp_path)
        task = Task(id=1, title="escalated", tags=[])

        for _ in range(3):
            await driver.advance(task)

        assert driver.phase_attempt(DriverPhase.HITL) == 0

    async def test_the_driver_still_holds_its_waiting_state(
        self, tmp_path: Path
    ) -> None:
        # Reporting IDLE must not be mistaken for the driver having finished —
        # it is still HITL_WAIT and must still be ticked so it sees the answer.
        driver = await self._driver(tmp_path)

        await driver.advance(Task(id=1, title="escalated", tags=[]))

        assert (driver.driver_state, driver.is_retired) == ("HITL_WAIT", False)

    async def test_a_genuine_failure_still_burns_an_attempt(
        self, tmp_path: Path
    ) -> None:
        # The distinction has to cut both ways, or the attempt counter stops
        # bounding retries at all.
        from issue_driver import IssueDriver

        class RealFailure(WaitingOnAHumanAdapter):
            async def run(self, task: Task, *, lease: object) -> PhaseOutcome:
                return PhaseOutcome(
                    ok=False, next_label=HITL_LABEL, detail="the phase blew up"
                )

        class Labels:
            async def read_stage_label(
                self, n: int, *, epoch: int = 0, phase_attempt: int = 0
            ) -> str:
                return HITL_LABEL

            def record_intent(self, *a: object, **k: object) -> None: ...
            def clear_intent(self, *a: object, **k: object) -> None: ...
            async def commit_stage_label(self, *a: object, **k: object) -> None: ...

        driver = IssueDriver(
            issue_number=1,
            driver_id="drv-1",
            repo_slug="acme/widgets",
            adapters={DriverPhase.HITL: RealFailure()},
            labels=Labels(),
            journal=DriverJournal(tmp_path / "journal.jsonl"),
            stage_labels={"HITL_WAIT": HITL_LABEL, "HITL_APPLY": HITL_LABEL},
            driver_state="HITL_WAIT",
        )

        await driver.advance(Task(id=1, title="escalated", tags=[]))

        assert driver.phase_attempt(DriverPhase.HITL) == 1


class TestADeclinedBoundaryIsCountedNeverWritten:
    """Defence in depth: no decline may put a write on the tick's hot path."""

    def test_a_decline_writes_no_row(self, tmp_path: Path) -> None:
        log = ShadowObservationLog(tmp_path / "shadow.jsonl")

        log.decline(TurnFailure.NOT_A_BOUNDARY)

        assert log.path.exists() is False

    def test_a_decline_is_still_counted(self, tmp_path: Path) -> None:
        log = ShadowObservationLog(tmp_path / "shadow.jsonl")

        log.decline(TurnFailure.NOT_A_BOUNDARY)

        assert log.summary()["not_a_boundary"] == 1

    def test_a_decline_does_not_inflate_the_observation_denominator(
        self, tmp_path: Path
    ) -> None:
        # ``observations`` is the denominator the agreement rate divides by, and
        # ADR-0137 B5's bar reads that rate. A decline is not an observation of
        # any director's judgement.
        log = ShadowObservationLog(tmp_path / "shadow.jsonl")

        log.decline(TurnFailure.NOT_A_BOUNDARY)

        assert log.summary()["observations"] == 0

    def test_the_kill_switch_decline_is_visible_in_the_rollup(
        self, tmp_path: Path
    ) -> None:
        # The one place an operator who just flipped the live kill switch would
        # look. Omitting it made the new control invisible where it is surfaced.
        log = ShadowObservationLog(tmp_path / "shadow.jsonl")

        log.decline(TurnFailure.DISABLED)

        assert log.summary()["disabled"] == 1
