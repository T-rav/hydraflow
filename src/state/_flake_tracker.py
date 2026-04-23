"""State accessors for FlakeTrackerLoop (spec §4.5)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class FlakeTrackerStateMixin:
    """Flake counts + per-test repair attempts."""

    _data: StateData

    def save(self) -> None: ...  # provided by CoreMixin

    def get_flake_counts(self) -> dict[str, int]:
        return dict(self._data.flake_counts)

    def set_flake_counts(self, counts: dict[str, int]) -> None:
        self._data.flake_counts = dict(counts)
        self.save()

    def get_flake_attempts(self, test_name: str) -> int:
        return int(self._data.flake_attempts.get(test_name, 0))

    def inc_flake_attempts(self, test_name: str) -> int:
        current = int(self._data.flake_attempts.get(test_name, 0)) + 1
        attempts = dict(self._data.flake_attempts)
        attempts[test_name] = current
        self._data.flake_attempts = attempts
        self.save()
        return current

    def clear_flake_attempts(self, test_name: str) -> None:
        attempts = dict(self._data.flake_attempts)
        attempts.pop(test_name, None)
        self._data.flake_attempts = attempts
        self.save()
