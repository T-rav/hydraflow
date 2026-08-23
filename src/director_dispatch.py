"""The director's canary actuator half, extracted from the observer (#11542).

``FableDirector`` does two separable jobs. It **observes** — reconstructs a
capsule, runs one isolated turn, applies ADR-0137's S4 assertion, validates the
reply and writes the comparison down — and, since #11541, it **dispatches**
whatever the broker admitted, for the one repository and the one phase a canary
dial names.

The second job is this mixin, and splitting it out is not tidiness. ADR-0137's
whole claim about the shadow director is that it has no authority; keeping the
part that *can* start a process in its own module makes that claim readable in
the file tree rather than only in a docstring. It is also what the mass sensor
asked for when the host class crossed its threshold: extract a cohesive cluster,
do not grandfather the size.

Two canaries live here, one per phase, each with its own dial, its own bound and
its own actuator — ``plan_broker`` / ``plan_worker_runner`` for ``PLAN`` and
``implement_broker`` / ``implement_worker_runner`` for ``IMPLEMENT``. They are
asked in order rather than merged: a single predicate covering both would be the
widening that "widen one role boundary at a time" forbids.

**This module holds no state of its own.** Every attribute it touches is the
host's, declared below as bare annotations — an annotation creates no class
attribute, so nothing here can shadow anything the host or a sibling mixin
defines (``tests/architecture/test_mixin_seam_stub_shadowing.py``, #11629). The
one *method* it borrows is declared under ``if TYPE_CHECKING:`` for the same
reason, so no runtime stub exists to win an MRO lookup.

And it writes no convergence state: ``ConvergenceLedger`` remains the sole owner
under ADR-0094's narrowing, and this module is on
``tests/architecture/test_director_no_authority.py``'s decision-path list beside
the observer it was cut from.
"""

from __future__ import annotations

import logging
from datetime import UTC, datetime
from typing import TYPE_CHECKING

from driver_contracts import (
    MAX_CAPSULE_RECEIPTS,
    ReceiptStatus,
    RejectionReason,
    WorkerRole,
    WriterLease,
)
from implement_broker import hibernation_reason, hibernation_refusal, writer_lease_for
from issue_driver_policy import phase_for_state
from plan_broker import CANARY_PHASE

if TYPE_CHECKING:
    import asyncio
    from collections.abc import Callable, Mapping

    from director_broker import BrokerVerdict
    from driver_contracts import (
        DirectorCommand,
        DriverLease,
        DriverPhase,
        WorkerDispatchRequest,
        WorkerReceipt,
    )
    from implement_worker_runner import ImplementWorkerRunner, WorktreeMeasurement
    from issue_driver import DriverAdvance, IssueDriver
    from models import Task
    from plan_broker import PlanCanaryLatch
    from plan_worker_runner import PlanWorkerRunner

logger = logging.getLogger("fable_director")

UNOBSERVED_DIGEST = "unobserved"
"""The worktree digests a boundary outside the Implement canary does not measure.

``WriterLease`` requires them, and #11537 deliberately left real measurement to
#11542. Outside that canary's bound there is still nothing to measure, so rather
than fabricate a plausible-looking sha the lease carries a value that reads as
what it is.

Defined here rather than in :mod:`fable_director` because the code that mints
it moved here with the actuator. :data:`implement_broker.UNMEASURED_TOKENS`
matches this exact string as well as its own, so a ``WorktreeState`` built
from these placeholders reads as unmeasured rather than as a tree somebody
looked at.
"""


class CanaryDispatchMixin:
    """Everything the director does *after* the broker has admitted a batch.

    Mixed into :class:`fable_director.FableDirector`, which owns every
    attribute below. They are annotations rather than assignments so this class
    contributes nothing to the runtime MRO but behaviour.
    """

    # -- the host's state, borrowed and never owned -------------------------
    _dispatcher: PlanWorkerRunner | None
    _is_covered: Callable[[DriverPhase | None], bool] | None
    _latch: PlanCanaryLatch | None
    _implement_dispatcher: ImplementWorkerRunner | None
    _implement_is_covered: Callable[[DriverPhase | None], bool] | None
    _receipts: dict[int, tuple[WorkerReceipt, ...]]
    _implementer_spawns: dict[int, frozenset[str]]
    _stage_labels: dict[str, str]
    _stop_event: asyncio.Event | None
    _is_enabled: Callable[[], bool] | None

    if TYPE_CHECKING:
        # The one method borrowed from the host. Declared here rather than
        # stubbed at runtime: a ``...`` body would create a real class
        # attribute that wins the MRO lookup over the host's implementation the
        # moment a second mixin exists, and return ``None`` silently (#11629).
        def _stopping(self) -> bool: ...

    async def _dispatch(
        self,
        task: Task,
        driver: IssueDriver,
        lease: DriverLease,
        command: DirectorCommand,
        verdict: BrokerVerdict,
        phase: DriverPhase,
        live_label: str,
        measured: WorktreeMeasurement | None,
    ) -> tuple[WorkerReceipt, ...]:
        """Run what the broker admitted, if this boundary is inside a canary.

        Two canaries now, one per phase, and they are asked in order rather
        than merged: each has its own dial, its own bound and its own actuator,
        and a single predicate covering both would be the widening that
        "widen one role boundary at a time" forbids. The bounds are mutually
        exclusive by construction — ``plan_broker.CANARY_PHASE`` is ``PLAN`` and
        ``implement_broker.CANARY_PHASE`` is ``IMPLEMENT`` — so the order below
        is readability rather than precedence.

        The gates, in this order, and each for its own reason:

        1. **the seam is wired** — a director constructed without an actuator
           (Classic and the deterministic controller build no director at all;
           a hand-built one in a test may omit either) returns here before
           evaluating anything else, so that path stays #11537's exactly. Under
           a production ``fable_director`` build **both actuators are always
           present**, and what stops a dispatch is clause 2, not this one. That
           is #11657's correction and it applies to both canaries: making
           construction conditional on the dial looked like a stronger
           default-off proof and was in fact the bug that made *arming* require
           a restart while only disarming was live;
        2. **the boundary is covered** — one repository and one phase, read
           live, so arming reaches the next boundary and clearing stops it;
        3. **the canary's own remaining fence** — the Plan slot latch, or for
           IMPLEMENT the hibernation check and the writer lease.

        The dispatcher's own per-request fence is passed down and re-evaluated
        immediately before each spawn, so a stop or an epoch bump *between* two
        children of one batch stops the second.
        """
        admitted = _admitted_requests(command, verdict)
        if not admitted:
            return ()
        if self._dispatcher is not None and self._covers(self._is_covered, phase):
            return await self._dispatch_plan(
                task, driver, lease, admitted, phase, live_label
            )
        if self._implement_dispatcher is not None and self._covers(
            self._implement_is_covered, phase
        ):
            return await self._dispatch_implement(
                task, driver, lease, admitted, phase, live_label, measured
            )
        return ()

    @staticmethod
    def _covers(
        predicate: Callable[[DriverPhase | None], bool] | None, phase: DriverPhase
    ) -> bool:
        """A canary's bound, read live. A missing predicate covers nothing."""
        return predicate is not None and predicate(phase)

    async def _dispatch_plan(
        self,
        task: Task,
        driver: IssueDriver,
        lease: DriverLease,
        admitted: tuple[WorkerDispatchRequest, ...],
        phase: DriverPhase,
        live_label: str,
    ) -> tuple[WorkerReceipt, ...]:
        """The Plan canary's actuator (#11541), unchanged by #11542.

        The repository's single brokered-Plan slot is the issue's first
        acceptance criterion from that phase, held as a fence.
        """
        dispatcher = self._dispatcher
        if dispatcher is None:  # pragma: no cover - narrowed by the caller
            return ()
        if self._latch is not None and not self._latch.claim(
            task.id, now=datetime.now(UTC)
        ):
            logger.info(
                "fable_director: #%d refused the brokered plan slot; #%s holds it",
                task.id,
                self._latch.holder,
            )
            return dispatcher.refuse(admitted, RejectionReason.CANARY_SLOT_HELD)
        receipts = await dispatcher.dispatch(
            admitted,
            task=task,
            lease=lease,
            phase=phase,
            fence=self._pre_spawn_fence(
                driver, lease, phase, live_label, self._is_covered
            ),
        )
        self._remember(task, receipts)
        return receipts

    async def _dispatch_implement(
        self,
        task: Task,
        driver: IssueDriver,
        lease: DriverLease,
        admitted: tuple[WorkerDispatchRequest, ...],
        phase: DriverPhase,
        live_label: str,
        measured: WorktreeMeasurement | None,
    ) -> tuple[WorkerReceipt, ...]:
        """The Implement canary's actuator (#11542): fenced, and one writer.

        Two refusals happen here rather than inside the runner, because both
        are facts only the director holds. A **hibernating** driver is parked on
        CI, a diagnostic or a human, and the right number of writers against its
        worktree is zero — the lease has already been revoked by
        :meth:`_hibernate_if_waiting`, and admitting a batch after that would
        immediately re-take it. An **unmeasurable** worktree means the fence
        cannot be armed at all, and ADR-0137 S4's rule applies unchanged: a
        boundary that cannot be proven is refused, never assumed.
        """
        dispatcher = self._implement_dispatcher
        if dispatcher is None:  # pragma: no cover - narrowed by the caller
            return ()
        blocked = hibernation_refusal(driver.driver_state)
        if blocked is not None:
            logger.info(
                "fable_director: #%d is hibernating (%s); no writer is dispatched",
                task.id,
                driver.driver_state,
            )
            return dispatcher.refuse(admitted, blocked)
        if measured is None:
            # Narrowing, not a second decision. ``_measure_worktree`` returns
            # ``None`` only for the cases the two clauses above already
            # refused, so this is unreachable - and a duplicate of the
            # runner's own "the fence could not be armed" check would be a
            # guard no test could kill, which #11541's mutation testing had to
            # delete once already. The runner owns that decision.
            return dispatcher.refuse(admitted, RejectionReason.WORKTREE_UNMEASURED)
        receipts = await dispatcher.dispatch(
            admitted,
            task=task,
            lease=lease,
            phase=phase,
            measured=measured,
            fence=self._pre_spawn_fence(
                driver,
                lease,
                phase,
                live_label,
                self._implement_is_covered,
                hibernates=True,
            ),
            driver_facts=self._driver_facts(driver, phase),
        )
        self._remember(task, receipts)
        self._remember_implementer_spawns(task, receipts)
        return receipts

    def _decision_ids(self, phase: DriverPhase) -> Mapping[str, str] | None:
        """The tier decisions behind this boundary's receipts, from the actuator
        that made them.

        Keyed on the phase rather than reading the Plan actuator unconditionally.
        Both actuators now always exist (#11657 removed the conditional
        construction that made arming need a restart), so "whichever one is not
        None" stopped being a valid way to ask which one ran — an IMPLEMENT
        boundary would have joined its receipts against the Plan runner's map
        and found nothing, silently emptying the very join the content-addressed
        decision id exists for.
        """
        if self._implement_dispatcher is not None and self._covers(
            self._implement_is_covered, phase
        ):
            return self._implement_dispatcher.last_decision_ids
        if self._dispatcher is not None:
            return self._dispatcher.last_decision_ids
        return None

    async def _measure_worktree(
        self, task: Task, driver: IssueDriver, phase: DriverPhase
    ) -> WorktreeMeasurement | None:
        """This issue's worktree, measured once per covered IMPLEMENT boundary.

        ``None`` everywhere else, and that is what keeps a shadow-mode or
        Plan-only host byte-identical: no dispatcher means no probe, no git
        subprocess and no change to the evidence recorded.

        Measured **once**, here, and then carried: the lease handed to the
        broker and the ``minted`` side of every worker's fence are the same
        reading. Measuring again inside the runner would make them two readings
        from two moments, which agree only by luck.

        **A hibernating driver is not measured**, and that is the difference
        between hibernating and merely refusing. A driver waiting on a human is
        ticked for as long as the human takes, so measuring it would put three
        ``git`` reads on a path the allocator reaches every poll interval for
        as long as nobody answers — the same hot-path defect #11537 had to fix
        at its cause once already. Nothing is dispatched from a wait, so
        nothing needs measuring.
        """
        dispatcher = self._implement_dispatcher
        if dispatcher is None or not self._covers(self._implement_is_covered, phase):
            return None
        if hibernation_reason(driver.driver_state) is not None:
            return None
        return await dispatcher.measure(task.id)

    def _writer_lease(
        self, lease: DriverLease, measured: WorktreeMeasurement | None
    ) -> WriterLease:
        """The single-writer lease the broker judges this batch against.

        Real digests inside the Implement canary; ``UNOBSERVED_DIGEST`` outside
        it, exactly as #11537 shipped. Stating the absence rather than
        fabricating a sha is the same rule in both directions.

        Precisely what each half does, because the two are easy to conflate.
        ``admit_dispatch`` fences on the lease's **identity, epoch and holder**
        — the holder is folded forward within a batch, which is what stops an
        implementer and a debugger being admitted together. It never reads the
        digest fields. The digests are fenced by
        :func:`implement_broker.check_worker_fence`, which compares two
        ``WorktreeState`` readings, because a frozen contract object cannot
        re-measure itself. Filling them in is what ADR-0137 asked of this
        phase: the object stops describing a tree nobody looked at.
        """
        if measured is None:
            return _unheld_writer_lease(lease)
        return writer_lease_for(lease, measured.state)

    def _driver_facts(
        self, driver: IssueDriver, phase: DriverPhase
    ) -> Callable[[], tuple[str, int, int, str]]:
        """The four ownership tokens, re-read at the moment the fence asks.

        A callable rather than a snapshot because these are precisely the
        values that move while a child runs: a fence handed a copy of the lease
        it is checking would verify unconditionally, which is the vacuous-guard
        shape #11541's mutation testing caught twice.

        The fourth token is the pipeline **label**, not the driver state, because
        that is what ``DriverLease.expected_stage_label`` holds. Passing the raw
        state here compared ``"READY"`` against ``"hydraflow-ready"`` and fenced
        every worker as preempted — a guard that fires on everything is as
        useless as one that fires on nothing, and it was the unit tests for the
        happy path that caught it.
        """

        def facts() -> tuple[str, int, int, str]:
            return (
                driver.driver_id,
                driver.epoch,
                driver.phase_attempt(phase),
                self._stage_labels.get(driver.driver_state, ""),
            )

        return facts

    def _remember(self, task: Task, receipts: tuple[WorkerReceipt, ...]) -> None:
        """Carry this boundary's receipts into the next capsule, bounded.

        Real receipts are real context for the next turn — ADR-0137 kept
        ``prior_receipts`` empty only for as long as no worker had run.
        """
        previous = self._receipts.get(task.id, ())
        self._receipts[task.id] = (previous + receipts)[-MAX_CAPSULE_RECEIPTS:]

    def _remember_implementer_spawns(
        self, task: Task, receipts: tuple[WorkerReceipt, ...]
    ) -> None:
        """Record which spawns actually implemented, so review can be fenced off them.

        Only ACCEPTED receipts count. A refused or superseded request produced
        no lineage at all, and inventing one would make the self-review fence
        refuse a reviewer over a worker that never ran.
        """
        spawns = {
            receipt.lineage.child_spawn_id
            for receipt in receipts
            if receipt.status is ReceiptStatus.ACCEPTED
            and receipt.lineage is not None
            and receipt.worker_role is WorkerRole.IMPLEMENTER
        }
        if not spawns:
            return
        self._implementer_spawns[task.id] = (
            self._implementer_spawns.get(task.id, frozenset()) | spawns
        )

    def _hibernate_if_waiting(self, task: Task, driver: IssueDriver) -> None:
        """Revoke this issue's writer lease while it waits on CI, a diagnostic or a human.

        ADR-0137 C6 already releases *capacity* for these three states. This is
        the same rule applied to *authority*, and it is the load-bearing half of
        #11542's fourth acceptance criterion: a driver parked on a barrier has
        no business holding a worktree, and a worker that comes back to find
        its lease revoked is still fenced on the way out, so revoking without
        waiting for it is safe.

        There is nothing to reconstruct on the way back. The next live boundary
        rebuilds the capsule from live state and re-measures the worktree from
        scratch, which is what "reconstruct from deterministic checkpoints"
        means in a runtime that never resumes a session.
        """
        dispatcher = self._implement_dispatcher
        if dispatcher is None:
            return
        reason = hibernation_reason(driver.driver_state)
        if reason is None:
            return
        dispatcher.revoke(task.id, RejectionReason.HIBERNATING)

    def _pre_spawn_fence(
        self,
        driver: IssueDriver,
        lease: DriverLease,
        phase: DriverPhase,
        live_label: str,
        is_covered: Callable[[DriverPhase | None], bool] | None,
        *,
        hibernates: bool = False,
    ) -> Callable[[], RejectionReason | None]:
        """Everything that can move between admission and a spawn, re-read.

        Deliberately not a second copy of ``admit_dispatch``: that table judged
        the *request* against a snapshot, and this re-reads the handful of facts
        that can change while a batch is running. The label fence reads the
        driver's own post-boundary view rather than issuing a fresh GitHub read
        — C1 makes that view a cache of the label the driver re-read at this
        boundary, and giving an observer its own port would hand authority to
        the one component that must not have any.
        """

        def fence() -> RejectionReason | None:
            # Rule order is part of the contract, so it is data rather than
            # control flow — the same shape ``admit_dispatch`` uses, and for the
            # same reason: first match wins, and the code an operator reads in a
            # receipt is reproducible from the inputs alone.
            current = self._stage_labels.get(driver.driver_state, "")
            rules: tuple[tuple[bool, RejectionReason], ...] = (
                (self._stopping(), RejectionReason.STOP_FENCE),
                (
                    self._is_enabled is not None and not self._is_enabled(),
                    RejectionReason.DRAINING,
                ),
                # The dial was cleared while this batch was running. Draining is
                # the honest code: the canary stopped accepting work, which is
                # not the request's fault and not a fence it failed.
                (
                    is_covered is not None and not is_covered(phase),
                    RejectionReason.DRAINING,
                ),
                # The driver entered a wait between the broker's admission and
                # this spawn. Its own code rather than DRAINING: the canary is
                # still accepting work, this issue just stopped having any.
                # Scoped to the IMPLEMENT fence rather than applied to both.
                # A hibernating driver has no business holding a *worktree*,
                # which is what this phase's workers take; a read-only Plan
                # worker takes nothing, and refusing one here would have
                # changed #11541's behaviour for an operator who never armed
                # this phase's dial - the exact thing the second dial exists
                # to prevent. #11543 may widen it, deliberately.
                (
                    hibernates and hibernation_reason(driver.driver_state) is not None,
                    RejectionReason.HIBERNATING,
                ),
                (driver.epoch != lease.epoch, RejectionReason.STALE_EPOCH),
                (
                    driver.phase_attempt(phase) != lease.phase_attempt,
                    RejectionReason.STALE_PHASE_ATTEMPT,
                ),
                (
                    bool(current) and current != lease.expected_stage_label,
                    RejectionReason.LIVE_LABEL_CHANGED,
                ),
            )
            return next((reason for fired, reason in rules if fired), None)

        return fence

    def _release_slot_if_moved_on(
        self, task: Task, advance: DriverAdvance, driver: IssueDriver
    ) -> None:
        """Free this repository's brokered-Plan slot once its issue leaves PLAN.

        The director is the only component that sees every boundary for every
        issue, so it is the only one that can tell when the holder has moved on.
        A slot released only by the TTL would idle the canary for the whole
        window after every successful plan.
        """
        if self._latch is None or self._latch.holder != task.id:
            return
        phase = advance.phase or phase_for_state(driver.driver_state)
        if phase is CANARY_PHASE and not driver.is_retired:
            return
        self._latch.release(task.id)
        self._receipts.pop(task.id, None)


def _admitted_requests(
    command: DirectorCommand, verdict: BrokerVerdict
) -> tuple[WorkerDispatchRequest, ...]:
    """The full requests behind the broker's admitted shadow dispatches.

    ``ShadowDispatch`` deliberately drops the task contract and the fencing
    tokens — it is a "what would have happened" record, not a command. The
    dispatcher needs the whole request, so the admitted set is used as a filter
    over the command rather than as a source, which also means a request the
    broker refused can never be reconstructed into one it dispatches.
    """
    admitted = {dispatch.request_id for dispatch in verdict.would_dispatch}
    return tuple(
        request for request in command.dispatches if request.request_id in admitted
    )


def _unheld_writer_lease(lease: DriverLease) -> WriterLease:
    """A single-writer lease at the driver's identity and epoch, held by no one."""
    return WriterLease(
        driver_id=lease.driver_id,
        epoch=lease.epoch,
        holder_request_id=None,
        worktree_base_digest=UNOBSERVED_DIGEST,
        worktree_head_digest=UNOBSERVED_DIGEST,
    )
