"""Factory-level control latches (#11208).

Persisted operator intent for the factory's run/stop state — distinct from
per-worker enable/disable (``_worker.py``). Currently just the
operator-stopped latch: set when an operator explicitly stops the factory via
``POST /api/control/stop``, cleared on ``POST /api/control/start``, and
consulted by boot-time autostart so a deliberate stop survives relaunch.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from models import StateData


class FactoryControlStateMixin:
    """Methods for the persisted operator-stopped latch."""

    _data: StateData

    # Host seams — implemented by the host class, declared here for typing
    # only. A runtime `...` body would be a real class attribute and would
    # win the MRO over a sibling mixin's implementation (#11629).
    if TYPE_CHECKING:

        def save(self) -> None: ...

    def get_operator_stopped(self) -> bool:
        """Return whether an operator explicitly stopped the factory last."""
        return self._data.operator_stopped

    def set_operator_stopped(self, stopped: bool) -> None:
        """Persist the operator-stopped latch."""
        self._data.operator_stopped = stopped
        self.save()
