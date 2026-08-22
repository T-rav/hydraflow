"""Durable GatewayCoverageLoop ceiling and regression counters.

Coverage snapshots themselves live in an atomically replaced metrics artifact;
the compact counter map records only the one-way ceiling milestone and later
direct-provider regressions without duplicating the snapshot in ``state.json``.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class GatewayCoverageStateMixin:
    """Durable milestone counters for the read-only coverage caretaker."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_gateway_coverage_attempts(self, key: str) -> int:
        return int(self._data.gateway_coverage_attempts.get(key, 0))

    def inc_gateway_coverage_attempts(self, key: str) -> int:
        attempts = dict(self._data.gateway_coverage_attempts)
        attempts[key] = int(attempts.get(key, 0)) + 1
        self._data.gateway_coverage_attempts = attempts
        self.save()
        return attempts[key]

    def clear_gateway_coverage_attempts(self, key: str) -> None:
        attempts = dict(self._data.gateway_coverage_attempts)
        attempts.pop(key, None)
        self._data.gateway_coverage_attempts = attempts
        self.save()

    def gateway_coverage_ceiling_achieved(self) -> bool:
        """Return whether a complete 100% spend window has been observed."""
        return self.get_gateway_coverage_attempts("ceiling-achieved") > 0

    def mark_gateway_coverage_ceiling_achieved(self) -> None:
        """Persist the one-way fleet-ratchet milestone."""
        if not self.gateway_coverage_ceiling_achieved():
            self.inc_gateway_coverage_attempts("ceiling-achieved")

    def record_gateway_coverage_regression(self) -> int:
        """Count post-ceiling windows containing direct-provider traffic."""
        return self.inc_gateway_coverage_attempts("post-ceiling-regression")
