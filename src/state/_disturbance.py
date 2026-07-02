"""DisturbanceDampenerLoop per-key attempt counters (ADR-0095)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class DisturbanceStateMixin:
    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_disturbance_dampener_attempts(self, key: str) -> int:
        return self._data.disturbance_dampener_attempts.get(key, 0)

    def bump_disturbance_dampener_attempts(self, key: str) -> int:
        n = self._data.disturbance_dampener_attempts.get(key, 0) + 1
        self._data.disturbance_dampener_attempts[key] = n
        self.save()
        return n

    def clear_disturbance_dampener_attempts(self, key: str) -> None:
        if key in self._data.disturbance_dampener_attempts:
            del self._data.disturbance_dampener_attempts[key]
            self.save()
