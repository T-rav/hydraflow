"""State mixin for AutoAgentPreflightLoop (spec §3.6)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class AutoAgentStateMixin:
    """Per-issue attempt counter + per-day spend tracker."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_auto_agent_attempts(self, issue: int) -> int:
        return int(self._data.auto_agent_attempts.get(str(issue), 0))

    def bump_auto_agent_attempts(self, issue: int) -> int:
        key = str(issue)
        current = int(self._data.auto_agent_attempts.get(key, 0))
        self._data.auto_agent_attempts[key] = current + 1
        self.save()
        return current + 1

    def clear_auto_agent_attempts(self, issue: int) -> None:
        key = str(issue)
        if key in self._data.auto_agent_attempts:
            del self._data.auto_agent_attempts[key]
            self.save()

    def get_auto_agent_daily_spend(self, date_iso: str) -> float:
        return float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))

    def add_auto_agent_daily_spend(self, date_iso: str, usd: float) -> float:
        current = float(self._data.auto_agent_daily_spend.get(date_iso, 0.0))
        new_total = current + float(usd)
        self._data.auto_agent_daily_spend[date_iso] = new_total
        self.save()
        return new_total
