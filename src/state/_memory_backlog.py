"""State accessors for MemoryBacklogLoop (ADR-0089)."""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class MemoryBacklogStateMixin:
    """Per-memory attempt counters for 3-strikes escalation."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_memory_backlog_attempts(self, key: str) -> int:
        return int(self._data.memory_backlog_attempts.get(key, 0))

    def inc_memory_backlog_attempts(self, key: str) -> int:
        current = int(self._data.memory_backlog_attempts.get(key, 0)) + 1
        attempts = dict(self._data.memory_backlog_attempts)
        attempts[key] = current
        self._data.memory_backlog_attempts = attempts
        self.save()
        return current

    def clear_memory_backlog_attempts(self, key: str) -> None:
        attempts = dict(self._data.memory_backlog_attempts)
        attempts.pop(key, None)
        self._data.memory_backlog_attempts = attempts
        self.save()
