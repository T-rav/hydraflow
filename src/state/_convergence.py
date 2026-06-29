"""Convergence ledger state (ADR: two-level convergence)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Literal

from models import ConvergenceLedger

if TYPE_CHECKING:
    from models import StateData


class ConvergenceStateMixin:
    """Per-issue convergence ledger accessors on the StateTracker."""

    _data: StateData

    def save(self) -> None: ...  # provided by StateTracker

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
            self._data.convergence_ledgers[key] = cl
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
        self._data.convergence_ledgers.pop(self._key(issue_number), None)
        self.save()
