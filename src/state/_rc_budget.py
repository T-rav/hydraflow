"""State accessors for RCBudgetLoop (spec §4.8)."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from models import StateData


class RCBudgetStateMixin:
    """Duration history + per-signal repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_rc_budget_duration_history(self) -> list[dict[str, Any]]:
        return [dict(entry) for entry in self._data.rc_budget_duration_history]

    def set_rc_budget_duration_history(self, history: list[dict[str, Any]]) -> None:
        self._data.rc_budget_duration_history = [dict(entry) for entry in history]
        self.save()

    def get_rc_budget_attempts(self, subject: str) -> int:
        return int(self._data.rc_budget_attempts.get(subject, 0))

    def inc_rc_budget_attempts(self, subject: str) -> int:
        current = int(self._data.rc_budget_attempts.get(subject, 0)) + 1
        attempts = dict(self._data.rc_budget_attempts)
        attempts[subject] = current
        self._data.rc_budget_attempts = attempts
        self.save()
        return current

    def clear_rc_budget_attempts(self, subject: str) -> None:
        attempts = dict(self._data.rc_budget_attempts)
        attempts.pop(subject, None)
        self._data.rc_budget_attempts = attempts
        self.save()
