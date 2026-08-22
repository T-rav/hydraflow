"""The operator-Start transition, shared by every door that starts a line.

Start expresses one intent — *run the pipeline* — and three call sites have to
apply it identically or they drift apart (#11611, where the registry branch of
``POST /api/control/start`` cleared only the latch and a launchd boot came up
``running: true`` with ``disabled_workers == ["plan", "triage"]``):

* ``POST /api/control/start`` — both branches (``dashboard_routes/_control_routes.py``)
* ``POST /api/runtimes/{slug}/start`` (``dashboard_routes/_state_routes.py``)
* boot-time autostart (``factory_autostart.maybe_autostart_host``)

It lives here rather than in the route layer so the boot path can import it
without depending on ``dashboard_routes``.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from orchestrator import HydraFlowOrchestrator
    from state import StateTracker

logger = logging.getLogger("hydraflow.operator_start")

# The workers that make up the board → READY path. An operator Start means
# "run the pipeline", so these come back on; every OTHER disabled worker is a
# deliberate kill-switch and stays off (#11611).
DEFAULT_PIPELINE_WORKERS: tuple[str, ...] = (
    "triage",
    "plan",
    "implement",
    "review",
    "hitl",
)


def apply_operator_start(
    state: StateTracker,
    orchestrator: HydraFlowOrchestrator | None = None,
    *,
    clear_latch: bool = True,
) -> set[str]:
    """Apply the operator-Start transition to one factory line.

    Two things happen:

    1. The persisted operator-stopped latch is cleared (#11208), unless
       ``clear_latch`` is False. The latch is factory-level, so the per-line
       and boot-autostart callers pass False: starting one repo — or a
       relaunch — must not clear an operator's deliberate Stop.
    2. The disable on :data:`DEFAULT_PIPELINE_WORKERS` is lifted, leaving every
       other entry in ``disabled_workers`` — a deliberate, durable per-worker
       kill-switch set through ``POST /api/control/bg-worker`` — untouched.

    Both the persisted set and the live orchestrator's in-memory enabled map
    are written, because each is authoritative for a different reader: state
    is what a cold boot restores from, the map is what running loops consult.
    ``StateRestorer._restore_disabled_workers`` only ever *adds* disabled
    flags, and ``RepoRuntime.start()`` reuses the same orchestrator object
    across a stop/start, so a state-only clear would leave a restarted line
    still holding ``plan: False`` in memory.

    Returns the names that were re-enabled — empty when nothing changed.
    """
    if clear_latch:
        state.set_operator_stopped(False)

    existing_disabled = state.get_disabled_workers()
    reenabled = existing_disabled & set(DEFAULT_PIPELINE_WORKERS)
    if not reenabled:
        return set()

    if orchestrator is not None:
        for name in sorted(reenabled):
            orchestrator.set_bg_worker_enabled(name, True)
    # Written last, and unconditionally: set_bg_worker_enabled recomputes the
    # persisted set from the orchestrator's in-memory map, which need not carry
    # kill-switches this process never loaded. This write is the authority.
    state.set_disabled_workers(existing_disabled - reenabled)
    logger.info("Operator Start re-enabled pipeline worker(s): %s", sorted(reenabled))
    return reenabled
