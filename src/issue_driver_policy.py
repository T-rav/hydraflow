"""The deterministic control law behind ``issue_controller`` scheduling (#11535).

This is the supervisory controller ADR-0099 names and ADR-0137 constrains: a
**pure** engine — no I/O, no config object, no clock of its own — that decides
which issues get a driver slot, when a driver may be preempted, and which
worker results are still live. ``driver_manager`` owns the slots and the
side effects; this module owns only the decisions, so every one of them is
replayable in a unit test. Same shape as :mod:`queue_strategy` and
:mod:`driver_contracts`.

Four decisions live here, one per adversarial finding they answer:

* :func:`counts_against_wip` — **C6/B2.** A driver that is not working releases
  its slot. Parked and HITL-waiting drivers are waiting on a *human*, and one
  slow human must not be able to consume the factory's whole WIP budget.
* :func:`select_admissions` — **B3.** Candidate order is P0-preempts-then-oldest,
  drawing its band vocabulary from :mod:`queue_strategy` rather than
  reimplementing it, with ``waiting_since`` as the anti-starvation key so a
  driver released under C6 is re-admitted ahead of newer arrivals.
* :func:`admit_phase_result` — **the fence.** Epoch and phase-attempt reject a
  result that arrived from a driver generation that no longer owns the issue.
  Rejection reasons are :class:`driver_contracts.RejectionReason` members, not
  new codes: one vocabulary for dispatch admission and result admission.
* :func:`is_preemptible` — **C3.** Preemption is legal at a phase boundary and
  nowhere else. Mid-subprocess preemption is a non-goal.

Nothing here reads the ``scheduling_model`` dial. Under Classic these functions
are simply never called; see :mod:`scheduling_model`.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from types import MappingProxyType
from typing import TYPE_CHECKING

from driver_contracts import DriverPhase, RejectionReason
from queue_strategy import PRIORITY_BANDS

if TYPE_CHECKING:
    from collections.abc import Iterable, Mapping
    from datetime import datetime


#: ``DriverState`` → the phase whose worker that state runs. ``DIAGNOSE`` maps
#: to ``REVIEW`` because it shares ``hydraflow-review`` (ADR-0137 B1c) and
#: ``HITL_APPLY``/``HITL_WAIT`` both map to ``HITL``. Terminal states have no
#: phase and are absent.
DRIVER_STATE_TO_PHASE: Mapping[str, DriverPhase] = MappingProxyType(
    {
        "TRIAGE": DriverPhase.TRIAGE,
        "PLAN": DriverPhase.PLAN,
        "READY": DriverPhase.IMPLEMENT,
        "REVIEW": DriverPhase.REVIEW,
        "DIAGNOSE": DriverPhase.REVIEW,
        "HITL_WAIT": DriverPhase.HITL,
        "HITL_APPLY": DriverPhase.HITL,
    }
)

#: States from which no further phase runs. A driver reaching one is retired
#: and its slot released.
TERMINAL_DRIVER_STATES: frozenset[str] = frozenset({"MERGED", "CLOSED", "ESCALATED"})

#: States in which the driver is waiting on a human or a barrier rather than
#: working. ADR-0137 C6: these **release** the global WIP slot. ``PARKED`` waits
#: on a barrier (``ci_wait``, ``epic_gap_barrier``); ``HITL_WAIT`` waits on an
#: operator correction.
NON_WORKING_DRIVER_STATES: frozenset[str] = frozenset({"PARKED", "HITL_WAIT"})

#: The band that preempts the ranking outright rather than taking a share of it.
#: Borrowed from ``queue_strategy`` so the two engines cannot disagree on which
#: band means "the factory is broken right now".
PREEMPT_BAND = PRIORITY_BANDS[0]


def counts_against_wip(driver_state: str) -> bool:
    """True when a driver in *driver_state* occupies a global WIP slot.

    A driver blocked on a congested stage semaphore **does** count — it is
    working, merely queued. A parked or HITL-waiting one does not, and neither
    does a retired one.
    """
    return (
        driver_state not in NON_WORKING_DRIVER_STATES
        and driver_state not in TERMINAL_DRIVER_STATES
    )


def phase_for_state(driver_state: str) -> DriverPhase | None:
    """The phase whose stage worker *driver_state* runs, or ``None`` if terminal."""
    return DRIVER_STATE_TO_PHASE.get(driver_state)


def is_preemptible(driver_state: str, *, at_phase_boundary: bool) -> bool:
    """ADR-0137 C3: a driver yields at a phase boundary and nowhere else.

    *at_phase_boundary* is the caller's assertion that the label for
    *driver_state* has just been committed, which is what makes yielding free
    and crash-safe. Mid-subprocess preemption is never legal, so a caller that
    is inside a running phase gets ``False`` regardless of state.
    """
    if not at_phase_boundary:
        return False
    return driver_state not in TERMINAL_DRIVER_STATES


@dataclass(frozen=True)
class SlotOccupancy:
    """Global and per-stage occupancy at view time (ADR-0137 C4).

    ``stage_caps`` reuses today's per-phase worker caps rather than replacing
    them: the allocator *respects* ``max_planners`` / ``max_workers`` etc., it
    does not remove the throttle. A phase absent from ``stage_caps`` is
    uncapped by that dimension and bounded only by ``max_in_flight``.
    """

    max_in_flight: int
    in_flight: int = 0
    per_stage: Mapping[DriverPhase, int] = field(default_factory=dict)
    stage_caps: Mapping[DriverPhase, int] = field(default_factory=dict)

    def has_global_room(self) -> bool:
        """True when another driver fits under ``max_in_flight``."""
        return self.in_flight < self.max_in_flight

    def has_stage_room(self, phase: DriverPhase | None) -> bool:
        """True when another driver fits under *phase*'s existing worker cap."""
        if phase is None:
            return True
        cap = self.stage_caps.get(phase)
        if cap is None:
            return True
        return self.per_stage.get(phase, 0) < cap

    def with_admitted(self, phase: DriverPhase | None) -> SlotOccupancy:
        """A copy reflecting one more admitted driver in *phase*.

        Lets :func:`select_admissions` rank a whole batch against a running
        occupancy without the caller mutating shared state mid-decision.
        """
        per_stage = dict(self.per_stage)
        if phase is not None:
            per_stage[phase] = per_stage.get(phase, 0) + 1
        return SlotOccupancy(
            max_in_flight=self.max_in_flight,
            in_flight=self.in_flight + 1,
            per_stage=per_stage,
            stage_caps=self.stage_caps,
        )


@dataclass(frozen=True)
class SchedulingView:
    """The frozen per-issue sensor record the control law reads (ADR-0137 B3).

    Deliberately a value type with no back-reference to the issue, the store or
    the driver: everything :func:`select_admissions` and :func:`admit_driver`
    need is on the record, so a decision can be replayed from a log line.
    """

    issue_number: int
    priority: str
    driver_state: str
    stage: str
    waiting_since: datetime
    blast_radius: str = "medium"

    @property
    def phase(self) -> DriverPhase | None:
        """The phase this view's state would run next."""
        return phase_for_state(self.driver_state)

    @property
    def band_rank(self) -> int:
        """Ordering index for the priority band; lower sorts first.

        Unknown and absent bands sort last, matching ``queue_strategy``'s
        treatment of unlabelled work — never dropped, just not preferred.
        """
        if self.priority in PRIORITY_BANDS:
            return PRIORITY_BANDS.index(self.priority)
        return len(PRIORITY_BANDS)


class AdmissionVerdict(StrEnum):
    """Why a candidate was or was not given a driver slot.

    Deterministic codes rather than free-form strings, so the canary's
    "zero duplicate dispatch / zero ownership leak" evidence is machine-
    comparable across runs — the same discipline ``RejectionReason`` applies to
    dispatch admission.
    """

    ADMIT = "admit"
    STOP_FENCED = "stop_fenced"
    DRAINING = "draining"
    ALREADY_DRIVEN = "already_driven"
    TERMINAL = "terminal"
    GLOBAL_WIP_FULL = "global_wip_full"
    STAGE_WIP_FULL = "stage_wip_full"


def admit_driver(
    view: SchedulingView,
    *,
    occupancy: SlotOccupancy,
    driven_issues: frozenset[int] = frozenset(),
    stop_requested: bool = False,
    draining: bool = False,
) -> AdmissionVerdict:
    """Pure admission decision for one candidate. First matching reason wins.

    Ordering mirrors :func:`driver_contracts.admit_dispatch` and is fail-closed
    for the same reason: global stop fences first, then ownership, then
    capacity. ``driven_issues`` is what makes a second driver for an already
    driven issue impossible — the single-owner invariant, checked before any
    capacity question.
    """
    gates: tuple[tuple[bool, AdmissionVerdict], ...] = (
        (stop_requested, AdmissionVerdict.STOP_FENCED),
        (draining, AdmissionVerdict.DRAINING),
        (view.issue_number in driven_issues, AdmissionVerdict.ALREADY_DRIVEN),
        (view.driver_state in TERMINAL_DRIVER_STATES, AdmissionVerdict.TERMINAL),
        (not occupancy.has_global_room(), AdmissionVerdict.GLOBAL_WIP_FULL),
        (
            not occupancy.has_stage_room(view.phase),
            AdmissionVerdict.STAGE_WIP_FULL,
        ),
    )
    for rejected, verdict in gates:
        if rejected:
            return verdict
    return AdmissionVerdict.ADMIT


def rank_candidates(views: Iterable[SchedulingView]) -> tuple[SchedulingView, ...]:
    """Order candidates: P0 first, then longest-waiting, then issue number.

    ``waiting_since`` is the anti-starvation key ADR-0137 C6 requires — a driver
    released while parked keeps its **original** admission-request time, so it
    is reconsidered ahead of issues that arrived while it waited. Issue number
    is the final tie-break purely so the order is total and reproducible.
    """
    return tuple(
        sorted(views, key=lambda v: (v.band_rank, v.waiting_since, v.issue_number))
    )


def select_admissions(
    views: Iterable[SchedulingView],
    *,
    occupancy: SlotOccupancy,
    driven_issues: frozenset[int] = frozenset(),
    stop_requested: bool = False,
    draining: bool = False,
) -> tuple[SchedulingView, ...]:
    """Rank candidates and take as many as global and stage capacity allow.

    Capacity is consumed as the batch is walked, so a stage cap reached partway
    through blocks only that stage: a lower-ranked candidate for a *different*
    phase still gets the remaining global slot rather than the whole batch
    stalling behind one saturated stage.
    """
    if stop_requested or draining:
        return ()
    admitted: list[SchedulingView] = []
    running = occupancy
    taken = set(driven_issues)
    for view in rank_candidates(views):
        verdict = admit_driver(
            view,
            occupancy=running,
            driven_issues=frozenset(taken),
        )
        if verdict is AdmissionVerdict.GLOBAL_WIP_FULL:
            break
        if verdict is not AdmissionVerdict.ADMIT:
            continue
        admitted.append(view)
        taken.add(view.issue_number)
        running = running.with_admitted(view.phase)
    return tuple(admitted)


def admit_phase_result(
    *,
    result_epoch: int,
    result_phase_attempt: int,
    lease_epoch: int,
    lease_phase_attempt: int,
    live_stage_label: str,
    accepted_stage_labels: frozenset[str],
    stop_requested: bool = False,
    committed_idempotency_keys: frozenset[str] = frozenset(),
    idempotency_key: str,
) -> RejectionReason | None:
    """Pure decision on whether one phase result may still be committed.

    ``None`` admits. The mirror image of :func:`driver_contracts.admit_dispatch`
    — same reason vocabulary, same first-match-wins ordering — applied to the
    *result* side, which is where the late-worker hazard actually lands: a
    driver killed mid-phase is recovered at a new epoch, and the original
    subprocess can still return afterwards.

    ``accepted_stage_labels`` is a *set*, not a single label, because "the label
    moved" is not by itself evidence of external interference. HydraFlow's stage
    workers commit their own transition label as part of their existing
    contract, so after a phase runs the issue legitimately carries either the
    label it started on or the one that phase was taking it to. Any *other*
    label is an operator dragging the card — ADR-0002's documented escape hatch
    — and yields ``LIVE_LABEL_CHANGED`` so the driver preempts rather than
    clobbering the edit. Callers making the pre-flight check pass the single
    starting label; callers validating a finished phase pass both.

    ``STOP_FENCE`` precedes the staleness checks so that after a stop no result
    commits at all, not even one whose fencing tokens are current. The
    idempotency check comes last: a duplicate of an already-committed boundary
    is not an error, it is a *re-entry*, and the caller treats
    ``DUPLICATE_IDEMPOTENCY_KEY`` as "already done, skip" rather than as a
    failure.
    """
    checks: tuple[tuple[bool, RejectionReason], ...] = (
        (stop_requested, RejectionReason.STOP_FENCE),
        (result_epoch != lease_epoch, RejectionReason.STALE_EPOCH),
        (
            result_phase_attempt != lease_phase_attempt,
            RejectionReason.STALE_PHASE_ATTEMPT,
        ),
        (
            live_stage_label not in accepted_stage_labels,
            RejectionReason.LIVE_LABEL_CHANGED,
        ),
        (
            idempotency_key in committed_idempotency_keys,
            RejectionReason.DUPLICATE_IDEMPOTENCY_KEY,
        ),
    )
    for rejected, reason in checks:
        if rejected:
            return reason
    return None


def boundary_idempotency_key(
    *,
    issue_number: int,
    epoch: int,
    phase: DriverPhase,
    phase_attempt: int,
) -> str:
    """The key one phase boundary commits under (ADR-0137 C8 step 2).

    Derived purely from the fencing tokens, so a replay of the same boundary
    after a crash produces the same key and is recognised as a re-entry, while
    a genuine retry at a new attempt or epoch does not collide with it.
    """
    return f"{issue_number}:{epoch}:{phase.value}:{phase_attempt}"


__all__ = [
    "DRIVER_STATE_TO_PHASE",
    "NON_WORKING_DRIVER_STATES",
    "PREEMPT_BAND",
    "TERMINAL_DRIVER_STATES",
    "AdmissionVerdict",
    "SchedulingView",
    "SlotOccupancy",
    "admit_driver",
    "admit_phase_result",
    "boundary_idempotency_key",
    "counts_against_wip",
    "is_preemptible",
    "phase_for_state",
    "rank_candidates",
    "select_admissions",
]
