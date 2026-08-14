"""Loop faceplates — one control-surface row per registered loop (#10826).

Pure join over the control register (#10824): ``control/fleet.yaml`` supplies
the census and classification, ``control/setpoints.yaml`` the (possibly
unsigned) setpoint, and the finder-calibration ledger (#10821) the noise-floor
sigma via :func:`control_register.measurement_noise_for`. No filesystem or
clock access here — loaders and timestamps are the route's job
(:mod:`dashboard_routes._diagnostics_routes`), same split as
:mod:`finder_faceplate`.

The LIVE half of a faceplate (PV, quiescence, last actuation) deliberately
does not appear in these rows: it already rides the ``BACKGROUND_WORKER_STATUS``
bus into the console's ``backgroundWorkers`` slice, and the UI joins the two
client-side (the LoopsPanel precedent). Serving it here would create a second,
slower copy of the same signal.
"""

from __future__ import annotations

from typing import Any

from control_register import (
    ControlClass,
    FleetEntry,
    SetpointSpec,
    measurement_noise_for,
)

#: Render order: regulator-shaped classes first — they carry the dials.
_CLASS_ORDER = {
    ControlClass.CONVERTIBLE: 0,
    ControlClass.ERROR_DRIVEN: 1,
    ControlClass.EXPLORATORY: 2,
    ControlClass.INFRASTRUCTURE: 3,
}


def _setpoint_cell(spec: SetpointSpec | None) -> dict[str, Any] | None:
    if spec is None:
        return None
    return {
        "value": spec.value,
        "band": spec.band,
        "units": spec.units,
        "direction": spec.direction,
        "signed": spec.active,
        "signed_by": spec.signed_by or None,
        "authority": spec.authority,
    }


def build_loop_faceplates(
    fleet: dict[str, FleetEntry],
    setpoints: dict[str, SetpointSpec],
    floors: dict[str, Any],
) -> list[dict[str, Any]]:
    """One faceplate row per fleet entry.

    Rows sort by control class (convertible/error-driven first — those carry
    the control surface) then worker name. ``floor_sigma`` is ``None`` when
    the loop has no finder join or the finder is uncalibrated — "cannot
    sense", never an invented variance.
    """
    rows: list[dict[str, Any]] = []
    for worker_name in sorted(
        fleet, key=lambda w: (_CLASS_ORDER[fleet[w].control_class], w)
    ):
        entry = fleet[worker_name]
        rows.append(
            {
                "worker_name": worker_name,
                "control_class": str(entry.control_class),
                "pv_label": entry.pv,
                "finder_id": entry.finder_id,
                "floor_sigma": measurement_noise_for(worker_name, fleet, floors),
                "setpoint": _setpoint_cell(setpoints.get(worker_name)),
            }
        )
    return rows
