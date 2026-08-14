"""Unit tests for the control register (#10824)."""

from __future__ import annotations

from pathlib import Path

from control_register import (
    ControlClass,
    FleetEntry,
    RegulatorVerdict,
    SetpointSpec,
    fleet_counts,
    load_fleet,
    load_setpoints,
    measurement_noise_for,
    regulate,
    setpoint_for,
)


def _write_control(tmp_path: Path, name: str, text: str) -> Path:
    (tmp_path / "control").mkdir(exist_ok=True)
    (tmp_path / "control" / name).write_text(text)
    return tmp_path


def _signed(**overrides) -> SetpointSpec:
    base = {
        "worker_name": "gate_health",
        "pv": "fleet pass rate",
        "units": "fraction",
        "value": 0.90,
        "band": 0.05,
        "direction": "above",
        "signed_by": "travis",
        "signed_date": "2026-08-13",
        "authority": "#10824",
    }
    base.update(overrides)
    return SetpointSpec(**base)


class TestSetpointLoading:
    def test_missing_file_means_no_setpoints(self, tmp_path: Path) -> None:
        assert load_setpoints(tmp_path) == {}

    def test_unsigned_spec_loads_but_is_inactive(self, tmp_path: Path) -> None:
        _write_control(
            tmp_path,
            "setpoints.yaml",
            "gate_health:\n  value: 0.9\n  band: 0.05\n  signed_by: null\n",
        )
        spec = load_setpoints(tmp_path)["gate_health"]
        assert not spec.active

    def test_signed_spec_is_active(self, tmp_path: Path) -> None:
        _write_control(
            tmp_path,
            "setpoints.yaml",
            "gate_health:\n  value: 0.9\n  band: 0.05\n  signed_by: travis\n"
            "  signed_date: '2026-08-13'\n",
        )
        spec = load_setpoints(tmp_path)["gate_health"]
        assert spec.active
        assert spec.signed_by == "travis"

    def test_missing_band_is_malformed_and_skipped(self, tmp_path: Path) -> None:
        _write_control(tmp_path, "setpoints.yaml", "gate_health:\n  value: 0.9\n")
        assert load_setpoints(tmp_path) == {}

    def test_zero_band_is_malformed_and_skipped(self, tmp_path: Path) -> None:
        # ADR-0120: the assembly is "deadband + hysteresis" — no deadband,
        # no regulator.
        _write_control(
            tmp_path,
            "setpoints.yaml",
            "gate_health:\n  value: 0.9\n  band: 0\n  signed_by: travis\n",
        )
        assert load_setpoints(tmp_path) == {}

    def test_syntactically_broken_yaml_degrades_to_no_setpoints(
        self, tmp_path: Path
    ) -> None:
        # Signing is a hand edit; a syntax slip must never crash a loop
        # cycle — it degrades to "no setpoints" (legacy behavior).
        _write_control(tmp_path, "setpoints.yaml", "gate_health:\n  value: [unclosed\n")
        assert load_setpoints(tmp_path) == {}

    def test_non_mapping_yaml_degrades_to_no_setpoints(self, tmp_path: Path) -> None:
        _write_control(tmp_path, "setpoints.yaml", "- just\n- a\n- list\n")
        assert load_setpoints(tmp_path) == {}

    def test_setpoint_for_returns_single_spec(self, tmp_path: Path) -> None:
        _write_control(
            tmp_path, "setpoints.yaml", "gate_health:\n  value: 0.9\n  band: 0.05\n"
        )
        assert setpoint_for(tmp_path, "gate_health") is not None
        assert setpoint_for(tmp_path, "sampled_audit") is None


class TestRegulate:
    def test_no_spec_is_unregulated(self) -> None:
        verdict = regulate(0.5, None, previously_quiescent=False)
        assert verdict == RegulatorVerdict(
            pv=0.5, error=0.0, quiescent=False, regulated=False
        )

    def test_unsigned_spec_is_unregulated(self) -> None:
        spec = _signed(signed_by="")
        verdict = regulate(0.5, spec, previously_quiescent=True)
        assert not verdict.regulated
        assert not verdict.quiescent

    def test_at_setpoint_enters_quiescence(self) -> None:
        verdict = regulate(0.92, _signed(), previously_quiescent=False)
        assert verdict.regulated
        assert verdict.quiescent
        assert verdict.error < 0  # healthy side

    def test_below_band_stays_acting(self) -> None:
        verdict = regulate(0.80, _signed(), previously_quiescent=False)
        assert verdict.regulated
        assert not verdict.quiescent
        assert verdict.error > 0

    def test_inside_deadband_does_not_enter_quiescence_from_acting(self) -> None:
        # 0.87: within band (0.90 - 0.05) but below the setpoint itself.
        # From acting mode, quiescence requires reaching the setpoint —
        # the Schmitt gap.
        verdict = regulate(0.87, _signed(), previously_quiescent=False)
        assert not verdict.quiescent

    def test_inside_deadband_holds_quiescence_once_entered(self) -> None:
        # Same 0.87 PV, but already quiescent: within the band, stay quiet.
        verdict = regulate(0.87, _signed(), previously_quiescent=True)
        assert verdict.quiescent

    def test_out_of_band_exits_quiescence(self) -> None:
        verdict = regulate(0.84, _signed(), previously_quiescent=True)
        assert not verdict.quiescent

    def test_direction_below(self) -> None:
        # e.g. a disagreement-rate setpoint: PV <= value is healthy.
        spec = _signed(value=0.10, band=0.05, direction="below")
        assert regulate(0.05, spec, previously_quiescent=False).quiescent
        assert not regulate(0.20, spec, previously_quiescent=False).quiescent
        # Inside the band from quiescence: hold.
        assert regulate(0.13, spec, previously_quiescent=True).quiescent


class TestFleet:
    def test_load_fleet_and_counts(self, tmp_path: Path) -> None:
        _write_control(
            tmp_path,
            "fleet.yaml",
            "gate_health:\n  class: convertible\n  pv: pass rate\n"
            "workspace_gc:\n  class: infrastructure\n"
            "wiki_rot_detector:\n  class: exploratory\n  finder_id: wiki_rot\n",
        )
        fleet = load_fleet(tmp_path)
        assert fleet["gate_health"].control_class is ControlClass.CONVERTIBLE
        assert fleet["wiki_rot_detector"].finder_id == "wiki_rot"
        counts = fleet_counts(fleet)
        assert counts[ControlClass.CONVERTIBLE] == 1
        assert counts[ControlClass.ERROR_DRIVEN] == 0

    def test_repo_fleet_file_loads(self) -> None:
        # The real, versioned register must always parse.
        fleet = load_fleet(Path(__file__).parent.parent)
        assert len(fleet) >= 60
        assert fleet["gate_health"].control_class is ControlClass.CONVERTIBLE

    def test_repo_setpoints_file_loads_and_is_unsigned(self) -> None:
        # The shipped gate_health proposal must stay inert until a human
        # signs it — if this assertion ever fails because someone signed it,
        # update the test to assert active instead (that flip is the point).
        specs = load_setpoints(Path(__file__).parent.parent)
        assert "gate_health" in specs


class TestMeasurementNoiseJoin:
    class _Floor:
        floor_sigma = 2.5

    def test_join_returns_sigma(self) -> None:
        fleet = {
            "wiki_rot_detector": FleetEntry(
                worker_name="wiki_rot_detector",
                control_class=ControlClass.EXPLORATORY,
                finder_id="wiki_rot",
            )
        }
        noise = measurement_noise_for(
            "wiki_rot_detector", fleet, {"wiki_rot": self._Floor()}
        )
        assert noise == 2.5

    def test_no_finder_join_returns_none(self) -> None:
        fleet = {
            "workspace_gc": FleetEntry(
                worker_name="workspace_gc",
                control_class=ControlClass.INFRASTRUCTURE,
            )
        }
        assert measurement_noise_for("workspace_gc", fleet, {}) is None
        assert measurement_noise_for("unknown", fleet, {}) is None

    def test_uncalibrated_finder_returns_none(self) -> None:
        fleet = {
            "wiki_rot_detector": FleetEntry(
                worker_name="wiki_rot_detector",
                control_class=ControlClass.EXPLORATORY,
                finder_id="wiki_rot",
            )
        }
        assert measurement_noise_for("wiki_rot_detector", fleet, {}) is None
