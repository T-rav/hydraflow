"""DisturbanceDampenerLoop per-key attempt counters (ADR-0095)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class DisturbanceStateMixin:
    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

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
