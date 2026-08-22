"""IssueDriver orchestration state accessors (HydraFlow v2)."""

from __future__ import annotations

from typing import TYPE_CHECKING

from models import (
    ConvergenceLedger,
    PendingStageTransition,
    PendingSubStateTransition,
)

if TYPE_CHECKING:
    from models import DriverState, StateData, SuspendRecord


class DriverStateMixin:
    """Per-issue IssueDriver state accessors on the StateTracker.

    Driver state lives on the issue's :class:`ConvergenceLedger`; these
    helpers encapsulate the read-modify-write-then-persist cycle the driver
    runtime performs on every transition. Mirrors the in-place-mutate +
    ``self.save()`` style of :class:`ConvergenceStateMixin`.
    """

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

        @staticmethod
        def _key(issue_id: int | str) -> str: ...

    def _ledger_or_new(self, issue_number: int) -> ConvergenceLedger:
        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number)
            self._data.convergence_ledgers[key] = cl
        return cl

    def get_driver_state(self, issue_number: int) -> str:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.driver_state if cl else "TRIAGE"

    def set_driver_state(self, issue_number: int, state: DriverState) -> None:
        self._ledger_or_new(issue_number).driver_state = state
        self.save()

    def suspend_driver(self, issue_number: int, record: SuspendRecord) -> None:
        self._ledger_or_new(issue_number).suspend = record
        self.save()

    def clear_suspend(self, issue_number: int) -> None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is not None and cl.suspend is not None:
            cl.suspend = None
            self.save()

    def set_pending_correction(self, issue_number: int, text: str) -> None:
        self._ledger_or_new(issue_number).pending_correction = text
        self.save()

    def take_pending_correction(self, issue_number: int) -> str | None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is None or cl.pending_correction is None:
            return None
        text = cl.pending_correction
        cl.pending_correction = None
        self.save()
        return text

    # --- ADR-0137 C5(a)/C9 transition intent -----------------------------
    #
    # Two slots, never one. C5(a) rule 1 clears the *stage* record whenever
    # exactly one pipeline label is present, which is the normal condition
    # for a sub-state transition — a shared slot would delete the sub-state
    # commit on the very path C9 exists to protect.

    def record_stage_transition(
        self,
        issue_number: int,
        *,
        from_label: str,
        to_label: str,
        epoch: int,
        phase_attempt: int,
    ) -> None:
        """Record where a label swap is going, **before** it is issued."""
        self._ledger_or_new(
            issue_number
        ).pending_stage_transition = PendingStageTransition(
            from_label=from_label,
            to_label=to_label,
            epoch=epoch,
            phase_attempt=phase_attempt,
        )
        self.save()

    def get_stage_transition(self, issue_number: int) -> PendingStageTransition | None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.pending_stage_transition if cl else None

    def clear_stage_transition(self, issue_number: int) -> None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is not None and cl.pending_stage_transition is not None:
            cl.pending_stage_transition = None
            self.save()

    def record_sub_state_transition(
        self,
        issue_number: int,
        *,
        from_state: DriverState,
        to_state: DriverState,
        epoch: int,
        phase_attempt: int,
    ) -> None:
        """Record entry into a sub-state that writes no pipeline label."""
        self._ledger_or_new(
            issue_number
        ).pending_sub_state_transition = PendingSubStateTransition(
            from_state=from_state,
            to_state=to_state,
            epoch=epoch,
            phase_attempt=phase_attempt,
        )
        self.save()

    def get_sub_state_transition(
        self, issue_number: int
    ) -> PendingSubStateTransition | None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.pending_sub_state_transition if cl else None

    def clear_sub_state_transition(self, issue_number: int) -> None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is not None and cl.pending_sub_state_transition is not None:
            cl.pending_sub_state_transition = None
            self.save()
