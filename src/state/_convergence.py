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

    def get_review_attempts(self, issue_number: int) -> int:
        """Return the current review attempt count for *issue_number* (default 0)."""
        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        return cl.get_attempts("review") if cl else 0

    def increment_review_attempts(self, issue_number: int) -> int:
        """Increment and return the new review attempt count for *issue_number*."""
        key = self._key(issue_number)
        cl = self._data.convergence_ledgers.get(key)
        if cl is None:
            cl = ConvergenceLedger(issue_number=issue_number)
            self._data.convergence_ledgers[key] = cl
        n = cl.increment_attempts("review")
        self.save()
        return n

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

    def min_review_passes_required(self, issue_number: int) -> int:
        """Return the minimum fresh-eyes review passes for *issue_number*.

        Defaults to 1 (low) when no blast radius has been recorded yet.
        Delegates the tier->count mapping to ``review_advisor`` so there is a
        single source of truth (ADR-0051 stratified table).
        """
        from review_advisor import min_review_passes_for_blast_radius  # noqa: PLC0415

        cl = self._data.convergence_ledgers.get(self._key(issue_number))
        radius = cl.blast_radius if cl else "low"
        return min_review_passes_for_blast_radius(radius)
