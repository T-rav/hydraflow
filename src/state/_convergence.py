"""Convergence ledger state (ADR: two-level convergence)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData


class ConvergenceStateMixin:
    """Per-issue convergence ledger accessors on the StateTracker."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    @staticmethod
    def _key(issue_id: int | str) -> str: ...  # provided by StateTracker

    def get_convergence_ledger(self, issue_number: int) -> ConvergenceLedger | None:
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.model_copy(deep=True) if cl else None

    def ensure_convergence_ledger(
        self,
        issue_number: int,
        blast_radius: Literal["low", "medium", "high"] = "low",
    ) -> ConvergenceLedger:
        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number, blast_radius=blast_radius)
            self._data.convergence_ledgers[key] = cl.model_copy(deep=True)
            self.save()
        return cl.model_copy(deep=True)

    def save_convergence_ledger(
        self, issue_number: int, ledger: ConvergenceLedger
    ) -> None:
        self._data.convergence_ledgers[self._key(issue_number)] = ledger.model_copy(
            deep=True
        )
        self.save()

    def clear_convergence_ledger(self, issue_number: int) -> None:
        if (
            self._data.convergence_ledgers.pop(self._key(issue_number), None)
            is not None
        ):
            self.save()

    # --- review attempt + blast-radius accessors (delegating to ledger) ---

    def set_quality_fix_attempts(self, issue_number: int, count: int) -> None:
        """Record the per-run quality-fix attempt count for *issue_number* into the ledger."""
        from models import StageRecord  # noqa: PLC0415

        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number)
            self._data.convergence_ledgers[key] = cl
        rec = cl.stage_state.get("quality_fix")
        if rec is None:
            cl.stage_state["quality_fix"] = StageRecord(attempts=count)
        else:
            rec.attempts = count
        self.save()

    def reset_review_attempts(self, issue_number: int) -> None:
        """Clear the review attempt counter for *issue_number*."""
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is not None and "review" in cl.stage_state:
            cl.stage_state["review"].attempts = 0
            self.save()

    def set_review_blast_radius(self, issue_number: int, radius: str) -> None:
        """Record the blast-radius tier for *issue_number*."""
        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number)
            self._data.convergence_ledgers[key] = cl
        cl.blast_radius = radius  # type: ignore[assignment]
        self.save()

    def get_review_blast_radius(self, issue_number: int) -> str | None:
        """Return the blast-radius tier for *issue_number*, or *None*."""
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.blast_radius if cl else None

    def iter_convergence_ledgers(self) -> list[tuple[int, ConvergenceLedger]]:
        """Return all ledgers as ``(issue_number, ledger)`` pairs (deep-copied)."""
        return [
            (int(k), v.model_copy(deep=True))
            for k, v in self._data.convergence_ledgers.items()
        ]

    def mark_oscillation_escalated(self, issue_number: int) -> None:
        """Set ``oscillation_escalated = True`` on *issue_number*'s ledger and save."""
        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number)
            self._data.convergence_ledgers[key] = cl
        cl.oscillation_escalated = True
        self.save()

    def reset_outer_laps(self, issue_number: int) -> None:
        """Reset the outer lap budget for *issue_number* after a gate-driven HITL escalation.

        Sets ``laps = 0`` and clears ``lap_signatures`` on the live ledger so a
        human-fixed, re-queued issue starts with a fresh outer budget and can
        loop back through the gate without immediately re-escalating.

        Preserves ``stage_state``, ``blast_radius``, ``converged``, and
        ``oscillation_escalated`` (caretaker dedup is separate by design).
        No-op when no ledger exists for *issue_number*.
        """
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        if cl is None:
            return
        cl.laps = 0
        cl.lap_signatures = []
        self.save()
