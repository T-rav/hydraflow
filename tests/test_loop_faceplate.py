"""Unit tests for the loop-faceplate pure builder (#10826)."""

from __future__ import annotations

from control_register import ControlClass, FleetEntry, SetpointSpec
from loop_faceplate import build_loop_faceplates


class _Floor:
    floor_sigma = 1.5


def _fleet() -> dict[str, FleetEntry]:
    return {
        "workspace_gc": FleetEntry(
            worker_name="workspace_gc",
            control_class=ControlClass.INFRASTRUCTURE,
        ),
        "gate_health": FleetEntry(
            worker_name="gate_health",
            control_class=ControlClass.CONVERTIBLE,
            pv="fleet pass rate",
        ),
        "wiki_rot_detector": FleetEntry(
            worker_name="wiki_rot_detector",
            control_class=ControlClass.EXPLORATORY,
            finder_id="wiki_rot",
        ),
        "erosion_metrics": FleetEntry(
            worker_name="erosion_metrics",
            control_class=ControlClass.ERROR_DRIVEN,
            pv="erosion vs baseline",
            finder_id="erosion_metrics",
        ),
    }


def _unsigned_spec() -> SetpointSpec:
    return SetpointSpec(
        worker_name="gate_health",
        pv="fleet pass rate",
        units="fraction",
        value=0.90,
        band=0.05,
        authority="#10824",
    )


def test_rows_sorted_regulator_classes_first() -> None:
    rows = build_loop_faceplates(_fleet(), {}, {})
    assert [r["worker_name"] for r in rows] == [
        "gate_health",  # convertible
        "erosion_metrics",  # error_driven
        "wiki_rot_detector",  # exploratory
        "workspace_gc",  # infrastructure
    ]


def test_unsigned_setpoint_marked_signed_false() -> None:
    rows = build_loop_faceplates(_fleet(), {"gate_health": _unsigned_spec()}, {})
    gate = next(r for r in rows if r["worker_name"] == "gate_health")
    assert gate["setpoint"] == {
        "value": 0.90,
        "band": 0.05,
        "units": "fraction",
        "direction": "above",
        "signed": False,
        "signed_by": None,
        "authority": "#10824",
    }


def test_signed_setpoint_carries_signer() -> None:
    spec = SetpointSpec(
        worker_name="gate_health",
        pv="fleet pass rate",
        units="fraction",
        value=0.90,
        band=0.05,
        signed_by="travis",
        signed_date="2026-08-13",
    )
    rows = build_loop_faceplates(_fleet(), {"gate_health": spec}, {})
    gate = next(r for r in rows if r["worker_name"] == "gate_health")
    assert gate["setpoint"]["signed"] is True
    assert gate["setpoint"]["signed_by"] == "travis"


def test_no_setpoint_is_none_not_zero() -> None:
    rows = build_loop_faceplates(_fleet(), {}, {})
    assert all(r["setpoint"] is None for r in rows)


def test_floor_sigma_joined_only_where_calibrated() -> None:
    rows = build_loop_faceplates(_fleet(), {}, {"wiki_rot": _Floor()})
    by_name = {r["worker_name"]: r for r in rows}
    assert by_name["wiki_rot_detector"]["floor_sigma"] == 1.5
    # Has a finder_id but no calibration → None ("cannot sense").
    assert by_name["erosion_metrics"]["floor_sigma"] is None
    # No finder join at all → None.
    assert by_name["workspace_gc"]["floor_sigma"] is None


def test_control_class_serialized_as_string() -> None:
    rows = build_loop_faceplates(_fleet(), {}, {})
    assert {r["control_class"] for r in rows} == {
        "convertible",
        "error_driven",
        "exploratory",
        "infrastructure",
    }
