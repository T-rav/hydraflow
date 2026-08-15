"""Boot-time factory autostart (#11208) — closes the server-up != factory-running gap.

``make factory`` (and the launchd liveness relaunch) previously only brought
up the dashboard/server: the runtime booted ``running:false`` and an operator
had to remember ``POST /api/control/start`` after every unattended relaunch
(stale-code heal, OOM recovery, reboot).

Two halves, mirroring ``scripts/liveness/boot_guard.py``:

* a PURE decision core (:func:`decide_autostart`) — a truth table over the
  ``factory_autostart`` config flag, the persisted operator-stopped latch, and
  whether the host line is already running. No I/O; fully unit-testable.
* a thin async I/O edge (:func:`maybe_autostart_host`) that calls
  :func:`decide_autostart` and, when it authorises a start, drives the host
  runtime through the exact same call ``POST /api/control/start`` makes
  (``host_runtime.start()`` + an ``ORCHESTRATOR_STATUS`` event).

Called from exactly one production call site: ``server.py``'s
``_run_with_dashboard``, right after the dashboard is healthy. Never called
from ``mockworld/sandbox_main.py`` or the in-process MockWorld harness — both
boot a ``HydraFlowDashboard`` directly, bypassing ``server.py`` entirely,
so MockWorld/sandbox scenarios never autostart. Enforced structurally by
``tests/architecture/test_factory_autostart_confinement.py``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import TYPE_CHECKING

from events import EventType, HydraFlowEvent
from models import OrchestratorStatusPayload

if TYPE_CHECKING:
    from config import HydraFlowConfig
    from events import EventBus
    from repo_runtime import RepoRuntime
    from state import StateTracker

logger = logging.getLogger("hydraflow.factory_autostart")


@dataclass(frozen=True)
class AutostartDecision:
    """The autostart decision core's verdict for one boot — no side effects."""

    should_start: bool
    reason: str


def decide_autostart(
    *,
    factory_autostart: bool,
    operator_stopped: bool,
    already_running: bool,
) -> AutostartDecision:
    """Pure: decide whether boot-time autostart should start the host line.

    Precedence: an already-running host is always a no-op (never redundantly
    started); otherwise the persisted operator-stopped latch wins over the
    ``factory_autostart`` flag even when it is enabled — a deliberate prior
    ``POST /api/control/stop`` must survive relaunch and stay down until the
    operator hits Start again. Only when the flag is on AND the operator
    hasn't stopped it AND it isn't already running does autostart fire.
    """
    if already_running:
        return AutostartDecision(False, "host line already running")
    if operator_stopped:
        return AutostartDecision(
            False,
            "operator explicitly stopped the factory — latch suppresses autostart",
        )
    if not factory_autostart:
        return AutostartDecision(False, "factory_autostart disabled")
    return AutostartDecision(
        True, "factory_autostart enabled, no operator-stopped latch, not running"
    )


async def maybe_autostart_host(
    *,
    config: HydraFlowConfig,
    host_runtime: RepoRuntime,
    state: StateTracker,
    event_bus: EventBus,
) -> bool:
    """Fire the host orchestrator start at boot, unless suppressed.

    Mirrors the registry branch of ``POST /api/control/start``
    (``dashboard_routes/_control_routes.py``) exactly: ``host_runtime.start()``
    then a reset ``ORCHESTRATOR_STATUS`` event, so the dashboard/UI observe
    boot-time autostart identically to an operator click. Returns whether it
    started the host line.
    """
    decision = decide_autostart(
        factory_autostart=config.factory_autostart,
        operator_stopped=state.get_operator_stopped(),
        already_running=host_runtime.running,
    )
    if not decision.should_start:
        logger.info("Factory autostart skipped: %s", decision.reason)
        return False
    logger.info("Factory autostart: %s", decision.reason)
    await host_runtime.start()
    await event_bus.publish(
        HydraFlowEvent(
            type=EventType.ORCHESTRATOR_STATUS,
            data=OrchestratorStatusPayload(status="running", reset=True),
        )
    )
    return True
