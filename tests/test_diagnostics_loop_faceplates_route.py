"""Tests for GET /api/diagnostics/loop-faceplates (#10826).

Serves the STATIC control-register half (fleet class + setpoint + floor
sigma); the live PV/quiescence half rides the BACKGROUND_WORKER_STATUS bus
and is joined client-side. Fail-soft: an unreadable fleet yields an error
marker with empty rows, never a 500.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402
from finder_calibration import (  # noqa: E402
    CalibrationLedger,
    FinderFloor,
    calibration_ledger_path,
)

# Fixed reference instant for ledger rows; passed explicitly, never compared
# against now() (wall-clock time-bomb rule).
_CALIBRATED_AT = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path / "data"
    cfg.repo_root = tmp_path / "repo"
    cfg.repo = "o/r"
    return cfg


def _client(cfg: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(cfg))
    return TestClient(app)


def _write_control(repo_root: Path, *, signed: bool = False) -> None:
    control = repo_root / "control"
    control.mkdir(parents=True, exist_ok=True)
    (control / "fleet.yaml").write_text(
        "gate_health:\n  class: convertible\n  pv: fleet pass rate\n"
        "wiki_rot_detector:\n  class: exploratory\n  finder_id: wiki_rot\n"
        "workspace_gc:\n  class: infrastructure\n"
    )
    signer = "signed_by: travis" if signed else "signed_by: null"
    (control / "setpoints.yaml").write_text(
        f"gate_health:\n  value: 0.90\n  band: 0.05\n  units: fraction\n  {signer}\n"
    )


def test_serves_register_rows_with_counts(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)

    body = _client(cfg).get("/api/diagnostics/loop-faceplates").json()

    assert [r["worker_name"] for r in body["loops"]] == [
        "gate_health",
        "wiki_rot_detector",
        "workspace_gc",
    ]
    assert body["counts"] == {
        "error_driven": 0,
        "convertible": 1,
        "exploratory": 1,
        "infrastructure": 1,
    }
    gate = body["loops"][0]
    assert gate["setpoint"]["signed"] is False
    assert gate["setpoint"]["value"] == 0.90


def test_floor_sigma_joined_from_calibration_ledger(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)
    CalibrationLedger(calibration_ledger_path(cfg.data_root)).record(
        FinderFloor(
            finder_id="wiki_rot",
            floor_mean=1.0,
            floor_sigma=0.5,
            sample_count=3,
            threshold=3,
            last_calibrated=_CALIBRATED_AT,
        )
    )

    body = _client(cfg).get("/api/diagnostics/loop-faceplates").json()

    rows = {r["worker_name"]: r for r in body["loops"]}
    assert rows["wiki_rot_detector"]["floor_sigma"] == 0.5
    assert rows["gate_health"]["floor_sigma"] is None


def test_unreadable_fleet_is_fail_soft(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    control = cfg.repo_root / "control"
    control.mkdir(parents=True)
    (control / "fleet.yaml").write_text("gate_health:\n  class: [broken\n")

    resp = _client(cfg).get("/api/diagnostics/loop-faceplates")

    assert resp.status_code == 200
    body = resp.json()
    assert body["loops"] == []
    assert body["error"] == "fleet-unreadable"


def test_missing_control_dir_is_fail_soft(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    cfg.repo_root.mkdir(parents=True, exist_ok=True)

    resp = _client(cfg).get("/api/diagnostics/loop-faceplates")

    assert resp.status_code == 200
    assert resp.json()["error"] == "fleet-unreadable"


def test_signed_setpoint_surfaces_signer(tmp_path: Path) -> None:
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root, signed=True)

    body = _client(cfg).get("/api/diagnostics/loop-faceplates").json()

    gate = body["loops"][0]
    assert gate["setpoint"]["signed"] is True
    assert gate["setpoint"]["signed_by"] == "travis"
