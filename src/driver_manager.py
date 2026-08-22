"""Capacity allocator for ``issue_controller`` scheduling (#11535).

One :class:`issue_driver.IssueDriver` owns one issue; this owns the drivers.
ADR-0099 calls it the capacity allocator; ADR-0137 gives it four jobs and this
module does exactly those four and nothing else:

* **Admit** (C4/B3) — hold at most ``driver_max_in_flight`` working drivers and
  respect the *existing* per-stage worker caps rather than replacing them. The
  ranking is :func:`issue_driver_policy.select_admissions`, a pure function, so
  the allocation decision is replayable from a log line.
* **Release** (C6/B2) — a parked or HITL-waiting driver gives its slot back.
  It keeps its original admission time, so it is reconsidered ahead of work that
  arrived while it waited and cannot be starved by newer arrivals.
* **Recover** (C2) — after a restart there are no drivers, only labels. A driver
  is rebuilt from the label the issue carries and takes the issue at
  ``journal.last_epoch + 1``, which fences anything still alive from the previous
  generation.
* **Fence on stop** — once the stop event is set nothing is admitted and nothing
  advances. "No post-stop spawns" is one of the three counters the canary bar
  measures (ADR-0137 B5), so it is enforced at the top of the tick rather than
  hoped for.

**It is not a second poller.** Candidates come from ``IssueStore``'s existing
per-stage queues through the existing claim protocol — the same
``get_plannable`` / ``get_implementable`` / ``get_reviewable`` calls the Classic
pools make, with the same ``release_in_flight`` release. Under
``issue_controller`` those pools are not running (the orchestrator registers the
driver loop *instead of* the plan/implement/review/HITL loops), so there is
exactly one consumer of each queue and duplicate dispatch is prevented
structurally rather than by a check.
"""

from __future__ import annotations

import logging
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Protocol

from driver_contracts import DriverPhase
from exception_classify import reraise_on_credit_or_bug
from issue_driver import AdvanceOutcome, IssueDriver
from issue_driver_policy import (
    NON_WORKING_DRIVER_STATES,
    ReconcileOutcome,
    SchedulingView,
    SlotOccupancy,
    StageIntent,
    StageReconciliation,
    counts_against_wip,
    phase_for_state,
    reconcile_stage_label,
    select_admissions,
)

if TYPE_CHECKING:
    from collections.abc import Mapping

    from driver_journal import DriverJournal
    from driver_ownership import DriverOwnershipRegistry
    from issue_driver import DriverAdvance, PhaseAdapter
    from models import PendingStageTransition, Task
    from ports import IssueStorePort, PRPort


class DriverTransitions(Protocol):
    """The ``ConvergenceLedger``-backed transition-intent slots (ADR-0137 C5/C9).

    Implemented by ``StateTracker`` via ``state._driver.DriverStateMixin``. The
    intent lives on the ledger rather than in the driver's own journal because
    ADR-0094 keeps per-issue durable state there, and because recovery needs it
    without depending on a file the driver happened to write.
    """

    def record_stage_transition(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None: ...

    def get_stage_transition(
        self, issue_number: int
    ) -> PendingStageTransition | None: ...

    def clear_stage_transition(self, issue_number: int) -> None: ...


logger = logging.getLogger("driver_manager")

#: Stage the queue getter for each phase corresponds to. Used only to release
#: the store's in-flight claim against the stage it was taken under.
_PHASE_STAGE: Mapping[DriverPhase, str] = {
    DriverPhase.PLAN: "plan",
    DriverPhase.IMPLEMENT: "ready",
    DriverPhase.REVIEW: "review",
    DriverPhase.HITL: "hitl",
}


@dataclass(frozen=True)
class DriverTickReport:
    """What one allocator tick did. Returned so the loop can log and meter it."""

    admitted: tuple[int, ...] = ()
    advanced: tuple[DriverAdvance, ...] = ()
    released: tuple[int, ...] = ()
    stopped: bool = False

    @property
    def did_work(self) -> bool:
        return bool(self.admitted or self.advanced or self.released)


class PipelineLabelAdapter:
    """Adapts ``PRPort`` to :class:`issue_driver.DriverLabels`.

    Reads go through ``get_issue_labels``, whose contract is explicitly
    fail-closed (#9575): a read failure raises rather than returning an empty
    list, so an unreadable issue can never be mistaken for an unlabelled one and
    silently preempted. Writes go through ``swap_pipeline_labels``, the same
    add-first primitive every phase already uses — the driver introduces no new
    way to move an issue.

    **Resolution is by recorded intent, not by priority** (ADR-0137 C5(a), as
    corrected by #11632). A mid-swap crash leaves two labels, and choosing the
    most advanced of them silently reverts every backward edge in this pipeline
    — a route-back and a HITL resume both look like a *regression* to a
    priority table. So the driver records where it is going before it goes, and
    this reads that record back. Priority remains only as rule 4: several
    labels and no usable intent, which a driver crash cannot produce because
    the record is written before the label add.
    """

    def __init__(
        self,
        prs: PRPort,
        *,
        ordered_labels: tuple[str, ...],
        transitions: DriverTransitions | None = None,
    ) -> None:
        self._prs = prs
        self._ordered_labels = ordered_labels
        self._transitions = transitions

    async def read_pipeline_labels(self, issue_number: int) -> frozenset[str]:
        """Every pipeline label the issue currently carries."""
        labels = await self._prs.get_issue_labels(issue_number)
        return frozenset(label for label in labels if label in self._ordered_labels)

    async def reconcile(
        self, issue_number: int, *, epoch: int, phase_attempt: int
    ) -> StageReconciliation:
        """Resolve the issue's true stage, completing an interrupted swap.

        The record is honoured only when it belongs to the incarnation being
        recovered, and it is cleared by the first reconciliation that observes
        it — which is what makes it safe to honour a record written under the
        epoch recovery has just fenced.
        """
        present = await self.read_pipeline_labels(issue_number)
        resolution = reconcile_stage_label(
            present_labels=present,
            priority_order=self._ordered_labels,
            intent=self._intent_for(issue_number),
            recovering_epoch=epoch,
            phase_attempt=phase_attempt,
        )
        if resolution.remove_label is not None and resolution.label is not None:
            # Finish the swap the dead incarnation began: one add already
            # landed, so re-issuing the swap removes the stale ``from_label``
            # through the same primitive rather than a bespoke delete.
            await self._prs.swap_pipeline_labels(issue_number, resolution.label)
        if resolution.clear_stage_intent and self._transitions is not None:
            self._transitions.clear_stage_transition(issue_number)
        if resolution.outcome is ReconcileOutcome.EXTERNAL_DRIFT:
            logger.warning(
                "driver: #%d carries a label outside its recorded transition "
                "(%s) — abandoning the swap and adopting the external label",
                issue_number,
                resolution.label,
            )
        return resolution

    async def read_stage_label(
        self, issue_number: int, *, epoch: int = 0, phase_attempt: int = 0
    ) -> str | None:
        """The issue's resolved pipeline stage, or ``None`` if it has no label.

        The caller supplies its own fencing tokens rather than letting the
        record vouch for itself: a record from a superseded epoch or a previous
        attempt must fall through to rule 4, not be honoured because it happens
        to be the only one on disk. This is the same call recovery makes, so a
        live driver and its own recovery can never disagree about which label
        is the truth.
        """
        resolution = await self.reconcile(
            issue_number, epoch=epoch, phase_attempt=phase_attempt
        )
        return resolution.label

    def _intent_for(self, issue_number: int) -> StageIntent | None:
        if self._transitions is None:
            return None
        recorded = self._transitions.get_stage_transition(issue_number)
        if recorded is None:
            return None
        return StageIntent(
            from_label=recorded.from_label,
            to_label=recorded.to_label,
            epoch=recorded.epoch,
            phase_attempt=recorded.phase_attempt,
        )

    def record_intent(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None:
        """C8 step 3': record where the swap is going, before issuing it."""
        if self._transitions is None:
            return
        self._transitions.record_stage_transition(
            issue_number,
            from_label=from_label,
            to_label=to_label,
            epoch=epoch,
            phase_attempt=phase_attempt,
        )

    def clear_intent(self, issue_number: int) -> None:
        """C8 step 5: the boundary is checkpointed; the intent is spent."""
        if self._transitions is not None:
            self._transitions.clear_stage_transition(issue_number)

    async def commit_stage_label(self, issue_number: int, label: str) -> None:
        await self._prs.swap_pipeline_labels(issue_number, label)


class DriverManager:
    """Holds ``<= max_in_flight`` live drivers and ticks each one boundary."""

    def __init__(
        self,
        *,
        store: IssueStorePort,
        labels: PipelineLabelAdapter,
        journal: DriverJournal,
        ownership: DriverOwnershipRegistry,
        adapters: Mapping[DriverPhase, PhaseAdapter],
        stage_labels: Mapping[str, str],
        repo_slug: str,
        max_in_flight: int,
        stage_caps: Mapping[DriverPhase, int],
    ) -> None:
        self._store = store
        self._labels = labels
        self._journal = journal
        self._ownership = ownership
        self._adapters = adapters
        self._stage_labels = stage_labels
        self._repo_slug = repo_slug
        self._max_in_flight = max_in_flight
        self._stage_caps = stage_caps
        self._drivers: dict[int, IssueDriver] = {}
        self._tasks: dict[int, Task] = {}
        self._waiting_since: dict[int, datetime] = {}

    # -- introspection ------------------------------------------------------

    @property
    def driven_issues(self) -> frozenset[int]:
        return frozenset(self._drivers)

    def occupancy(self) -> SlotOccupancy:
        """Current global and per-stage occupancy, C6 release rule applied."""
        per_stage: dict[DriverPhase, int] = {}
        in_flight = 0
        for driver in self._drivers.values():
            if not counts_against_wip(driver.driver_state):
                continue
            in_flight += 1
            phase = phase_for_state(driver.driver_state)
            if phase is not None:
                per_stage[phase] = per_stage.get(phase, 0) + 1
        return SlotOccupancy(
            max_in_flight=self._max_in_flight,
            in_flight=in_flight,
            per_stage=per_stage,
            stage_caps=self._stage_caps,
        )

    # -- the tick -----------------------------------------------------------

    async def tick(self, *, stop_requested: bool = False) -> DriverTickReport:
        """Retire what finished, admit what fits, advance every live driver once.

        The order is load-bearing. Retiring first returns the slots freed by the
        previous tick, so admission sees true capacity. Admitting *before*
        advancing is what removes the dead time the whole design exists to
        remove: a newly admitted issue runs its first phase on the tick it was
        admitted, not a full poll interval later. A driver that retires during
        this tick's advance frees its slot at the top of the next one, so
        admission latency for a queued issue stays bounded by one poll interval
        — the same bound Classic has.
        """
        if stop_requested:
            return DriverTickReport(stopped=True)

        released = self._retire_finished()
        candidates = self._collect_candidates()
        admitted = self._admit([task for task, _stage in candidates])
        self._return_unadmitted(candidates)
        advanced = await self._advance_all(stop_requested=stop_requested)
        return DriverTickReport(
            admitted=tuple(admitted), advanced=tuple(advanced), released=tuple(released)
        )

    def _collect_candidates(self) -> list[tuple[Task, str]]:
        """Pull candidates from each stage queue through the existing claim path.

        The window is sized to free capacity rather than being unbounded:
        ``get_*`` splices a task out of its deque and stamps ``_in_flight``, so
        every task pulled is a task the allocator has taken responsibility for
        putting somewhere. Pulling more than can be admitted is not free.
        """
        free = max(self._max_in_flight - self.occupancy().in_flight, 0)
        window = max(free, 1)
        pulled: list[tuple[Task, str]] = []
        for getter, phase in (
            (self._store.get_plannable, DriverPhase.PLAN),
            (self._store.get_implementable, DriverPhase.IMPLEMENT),
            (self._store.get_reviewable, DriverPhase.REVIEW),
        ):
            stage = _PHASE_STAGE[phase]
            for task in getter(window):
                pulled.append((task, stage))
                if task.id in self._drivers:
                    # A fresh copy for a driver that already owns this issue:
                    # the body may have been edited and the label may have
                    # moved. Ownership lives in the registry, so the store's
                    # claim is handed straight back.
                    self._tasks[task.id] = task
        return pulled

    def _return_unadmitted(self, candidates: list[tuple[Task, str]]) -> None:
        """Put back every pulled task that did not end up with a driver.

        Without this the tick is a work leak: ``get_plannable`` has already
        removed the task from its deque and stamped it in-flight, and
        ``release_in_flight`` alone only clears the stamp — the task would not
        reappear until the next full GitHub poll, so a global WIP cap would
        quietly delay every issue it declined by a whole ``data_poll_interval``.
        ``enqueue_transition`` is the store's existing eager re-queue path, the
        same one ``PlanPhase`` uses for the standalone issues an epic cycle
        defers, so a declined candidate is reconsidered on the very next tick.
        """
        for task, stage in candidates:
            if task.id not in self._drivers:
                self._store.enqueue_transition(task, stage)

    def _admit(self, candidates: list[Task]) -> list[int]:
        views: list[SchedulingView] = []
        by_number: dict[int, Task] = {}
        now = datetime.now(UTC)
        for task in candidates:
            if task.id in self._drivers:
                continue
            state = self._state_from_task(task)
            if state is None:
                continue
            by_number[task.id] = task
            views.append(
                SchedulingView(
                    issue_number=task.id,
                    priority=_band_of(task),
                    driver_state=state,
                    stage=self._stage_labels.get(state, ""),
                    waiting_since=self._waiting_since.setdefault(task.id, now),
                )
            )
        selected = select_admissions(
            views,
            occupancy=self.occupancy(),
            driven_issues=self.driven_issues,
        )
        admitted: list[int] = []
        for view in selected:
            driver = self._build_driver(view.issue_number, view.driver_state)
            if not self._ownership.claim(
                view.issue_number, driver_id=driver.driver_id, epoch=driver.epoch
            ):
                logger.warning(
                    "driver_manager: #%d already owned; not admitting a second driver",
                    view.issue_number,
                )
                continue
            self._drivers[view.issue_number] = driver
            self._tasks[view.issue_number] = by_number[view.issue_number]
            admitted.append(view.issue_number)
        return admitted

    def _build_driver(self, issue_number: int, driver_state: str) -> IssueDriver:
        prior = self._journal.last_epoch(issue_number)
        epoch = 0 if prior is None else prior + 1
        return IssueDriver(
            issue_number=issue_number,
            driver_id=f"drv-{issue_number}-{uuid.uuid4().hex[:8]}",
            repo_slug=self._repo_slug,
            adapters=self._adapters,
            labels=self._labels,
            journal=self._journal,
            stage_labels=self._stage_labels,
            driver_state=driver_state,
            epoch=epoch,
        )

    async def _advance_all(self, *, stop_requested: bool) -> list[DriverAdvance]:
        advances: list[DriverAdvance] = []
        for issue_number, driver in list(self._drivers.items()):
            if driver.driver_state in NON_WORKING_DRIVER_STATES:
                # C6: parked / waiting on a human. The slot is already released
                # by ``occupancy``; do not spin a phase against it.
                continue
            task = self._tasks.get(issue_number)
            if task is None:
                continue
            try:
                advance = await driver.advance(task, stop_requested=stop_requested)
            except Exception as exc:
                reraise_on_credit_or_bug(exc)
                logger.warning(
                    "driver_manager: driver for #%d raised: %s", issue_number, exc
                )
                continue
            advances.append(advance)
            if advance.outcome is AdvanceOutcome.COMMITTED:
                logger.info(
                    "driver_manager: #%d committed %s -> %s",
                    issue_number,
                    advance.phase.value if advance.phase else "?",
                    driver.driver_state,
                )
        return advances

    def _retire_finished(self) -> list[int]:
        released: list[int] = []
        for issue_number, driver in list(self._drivers.items()):
            if not driver.is_retired:
                continue
            self._ownership.release(
                issue_number, driver_id=driver.driver_id, epoch=driver.epoch
            )
            self._store.release_in_flight({issue_number})
            del self._drivers[issue_number]
            self._tasks.pop(issue_number, None)
            self._waiting_since.pop(issue_number, None)
            released.append(issue_number)
        return released

    def release_all(self) -> None:
        """Drop every driver and claim. Called on factory stop."""
        for issue_number, driver in list(self._drivers.items()):
            self._ownership.release(
                issue_number, driver_id=driver.driver_id, epoch=driver.epoch
            )
            self._store.release_in_flight({issue_number})
        self._drivers.clear()
        self._tasks.clear()
        self._waiting_since.clear()

    # -- helpers ------------------------------------------------------------

    def _state_from_task(self, task: Task) -> str | None:
        """The driver state implied by the task's most advanced pipeline label.

        Recovery reads labels, never a cache (ADR-0137 C2). ``None`` means the
        issue carries no label this preset drives, so it is not a candidate.
        """
        best: tuple[int, str] | None = None
        for state, label in self._stage_labels.items():
            if label not in task.tags:
                continue
            phase = phase_for_state(state)
            rank = _PHASE_RANK.get(phase, -1) if phase is not None else -1
            if best is None or rank > best[0]:
                best = (rank, state)
        if best is None:
            return None
        state = best[1]
        return state if phase_for_state(state) in self._adapters else None


#: Forward ordering of phases, so an issue carrying two pipeline labels after a
#: mid-swap crash resolves to the more advanced one — the same
#: most-advanced-wins rule ``IssueStore._compute_stage_map`` applies.
_PHASE_RANK: Mapping[DriverPhase, int] = {
    DriverPhase.TRIAGE: 0,
    DriverPhase.PLAN: 1,
    DriverPhase.IMPLEMENT: 2,
    DriverPhase.REVIEW: 3,
    DriverPhase.HITL: 4,
}


def _band_of(task: Task) -> str:
    """The task's priority band, reusing ``queue_strategy``'s vocabulary."""
    from queue_strategy import band_of

    return band_of(task)
