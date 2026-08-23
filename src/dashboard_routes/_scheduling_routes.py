"""Operator visibility for the scheduling dials and the shadow director (#11537).

#11537's fourth acceptance criterion is that operator status shows the
**desired** and **effective** scheduling mode and the **hypothetical worker
tree**. Those are three separate things and this endpoint keeps them separate,
because collapsing them is how an operator comes to believe a mode is running
that is not:

* **desired** is what the config says. Both dials are restart-required, so a
  config edit changes this immediately and changes nothing else.
* **effective** is what the running process actually built — whether a
  ``DriverManager`` exists, whether a ``FableDirector`` exists, and whether the
  director is still attached. That last one matters: a director that fails its
  startup boundary proof is *detached* for the run (ADR-0137 S1/S4), so desired
  can read ``fable_director`` while effective honestly reports that nothing is
  observing.
* **hypothetical worker tree** is what the director would have dispatched at
  recent boundaries. Every node carries ``dispatched: false``, and while the
  Plan canary is disarmed the summary carries ``workers_dispatched: 0`` —
  which is then an invariant rather than a status.

#11541 armed dispatch for one repository at ``PLAN``, and two things here
follow from that. ``workers_dispatched`` is now **counted** rather than
asserted, so it stops reading zero exactly when it stops being true; and
``director_dispatch_armed`` is read off the *config*, not off
``SchedulingPreset``, whose field is False on every preset and always will be
— arming is per-repository and live, and reporting the preset's field would
tell an operator with an armed canary that dispatch was not armed.

Read-only. Nothing here can change a dial; the dials live on the settings
screen, where the runtime dials are restart-required and the canary dial is
not.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from fastapi.responses import JSONResponse

from scheduling_model import SELECTABLE_PRESETS, resolve_preset

if TYPE_CHECKING:
    from fastapi import APIRouter

    from config import HydraFlowConfig
    from dashboard_routes._routes import RouteContext

logger = logging.getLogger("hydraflow.dashboard")


def _desired(config: HydraFlowConfig) -> dict[str, Any]:
    """What the operator asked for, straight off the config."""
    preset = resolve_preset(config.scheduling_model, config.execution_runtime)
    return {
        "preset": preset.name,
        "scheduling_model": config.scheduling_model.value,
        "execution_runtime": config.execution_runtime.value,
        "uses_issue_driver": preset.uses_issue_driver,
        "uses_fable_director": preset.uses_fable_director,
        # Read off the CONFIG, not off the preset (#11541). Arming is per-repo
        # and live, so the preset's field is False on every preset and always
        # will be — reporting it here would tell an operator with an armed
        # canary that dispatch is not armed, which is the one thing this
        # endpoint exists to stop happening.
        "director_dispatch_armed": config.fable_plan_canary_armed(),
        "plan_canary_repo": str(config.fable_plan_canary_repo or ""),
        # The two dials above differ in liveness and an operator has to know
        # which: selecting the runtime needs a restart, arming the canary does
        # not, and a single restart_required flag over both would be false half
        # the time.
        "restart_required": True,
        "plan_canary_restart_required": False,
    }


def _effective(orch: object | None) -> dict[str, Any]:
    """What the running process actually built. ``None`` when nothing is running.

    Read off the live service registry rather than re-derived from config,
    because the whole value of an "effective" view is that it can *disagree*
    with the desired one — a stale process, or a director detached after a
    failed boundary proof.
    """
    if orch is None:
        return {"running": False}
    svc = getattr(orch, "_svc", None)
    manager = getattr(svc, "driver_manager", None) if svc is not None else None
    director = getattr(svc, "fable_director", None) if svc is not None else None
    return {
        "running": True,
        "driver_manager_built": manager is not None,
        "fable_director_built": director is not None,
        # A director can be built and then detached for the run when it fails
        # its startup boundary proof — the honest answer to "is anything
        # observing?" is this one, not whether the object exists.
        "director_attached": bool(manager is not None and manager.has_observer),
        "drivers_in_flight": (
            sorted(manager.driven_issues) if manager is not None else []
        ),
    }


def _shadow(orch: object | None, limit: int) -> dict[str, Any]:
    """The shadow comparison rollup and the hypothetical worker tree.

    ``active`` keys on whether the allocator is actually holding the observer,
    not on whether the object exists. A director that fails its startup boundary
    proof is *detached* for the run, and reporting ``active: true`` for it would
    reproduce the exact confusion this endpoint splits desired from effective to
    prevent — an operator would see the shadow section switched on and the
    director section switched off in the same response.
    """
    svc = getattr(orch, "_svc", None) if orch is not None else None
    director = getattr(svc, "fable_director", None) if svc is not None else None
    manager = getattr(svc, "driver_manager", None) if svc is not None else None
    attached = bool(manager is not None and manager.has_observer)
    if director is None or not attached:
        return {"active": False, "observations": []}
    log = director.shadow_log
    return {
        "active": True,
        "summary": log.summary(),
        "observations": [
            observation.model_dump(mode="json") for observation in log.recent(limit)
        ],
    }


def register(router: APIRouter, ctx: RouteContext) -> None:
    """Register the read-only scheduling-status route on *router*."""

    @router.get("/api/scheduling/status")
    async def get_scheduling_status(limit: int = 20) -> JSONResponse:
        """Desired vs effective scheduling mode, plus the shadow director view."""
        orch = ctx.get_orchestrator()
        bounded = max(1, min(limit, 50))
        return JSONResponse(
            {
                "desired": _desired(ctx.config),
                "effective": _effective(orch),
                "shadow": _shadow(orch, bounded),
                "selectable_presets": [
                    {
                        "name": preset.name,
                        "scheduling_model": preset.scheduling_model.value,
                        "execution_runtime": preset.execution_runtime.value,
                        "reason": preset.reason,
                    }
                    for preset in SELECTABLE_PRESETS
                ],
            }
        )
