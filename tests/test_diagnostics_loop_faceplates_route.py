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
    date = "  signed_date: 2026-08-15\n" if signed else ""
    (control / "setpoints.yaml").write_text(
        f"gate_health:\n  value: 0.90\n  band: 0.05\n  units: fraction\n  {signer}\n"
        f"{date}"
    )


def _ctx_with_orchestrator(cfg: MagicMock, orch: object | None) -> MagicMock:
    """A RouteContext stand-in resolving ``(cfg, state, bus, get_orch)``.

    Only ``resolve_runtime`` is exercised by this endpoint; the orchestrator
    getter yields *orch* (``None`` = factory not started).
    """
    ctx = MagicMock()
    ctx.resolve_runtime.return_value = (
        cfg,
        MagicMock(),
        MagicMock(),
        lambda: orch,
    )
    return ctx


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
    assert gate["setpoint"]["signed_date"] == "2026-08-15"


def test_interval_s_resolved_from_live_orchestrator(tmp_path: Path) -> None:
    """#11232: with a ctx + started factory, each row carries the loop's
    effective tick interval (weekly for gate_health) so the client can render
    "awaiting next tick (due last_tick + interval)"."""
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)
    orch = MagicMock()
    orch.get_bg_worker_interval = lambda name: {
        "gate_health": 604800,
        "wiki_rot_detector": 900,
    }[name]
    app = FastAPI()
    app.include_router(
        build_diagnostics_router(cfg, ctx=_ctx_with_orchestrator(cfg, orch))
    )

    body = TestClient(app).get("/api/diagnostics/loop-faceplates").json()

    rows = {r["worker_name"]: r for r in body["loops"]}
    assert rows["gate_health"]["interval_s"] == 604800
    assert rows["wiki_rot_detector"]["interval_s"] == 900


def test_interval_s_none_when_orchestrator_not_started(tmp_path: Path) -> None:
    """Fail-soft: no live orchestrator → interval_s None ("due unknown"),
    never a 500 — the register half still serves."""
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)
    app = FastAPI()
    app.include_router(
        build_diagnostics_router(cfg, ctx=_ctx_with_orchestrator(cfg, None))
    )

    resp = TestClient(app).get("/api/diagnostics/loop-faceplates")

    assert resp.status_code == 200
    assert all(r["interval_s"] is None for r in resp.json()["loops"])


def test_interval_s_fail_soft_when_runtime_resolve_raises(tmp_path: Path) -> None:
    """A malformed runtime (resolve_runtime raises) degrades to "due unknown"
    for every row — never a 500 — the register half still serves."""
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)
    ctx = MagicMock()
    ctx.resolve_runtime.side_effect = AttributeError("no runtime")
    app = FastAPI()
    app.include_router(build_diagnostics_router(cfg, ctx=ctx))

    resp = TestClient(app).get("/api/diagnostics/loop-faceplates")

    assert resp.status_code == 200
    assert all(r["interval_s"] is None for r in resp.json()["loops"])


def test_interval_s_none_without_ctx(tmp_path: Path) -> None:
    """Legacy single-repo callers (no ctx) get interval_s None everywhere."""
    cfg = _config(tmp_path)
    _write_control(cfg.repo_root)

    body = _client(cfg).get("/api/diagnostics/loop-faceplates").json()

    assert all(r["interval_s"] is None for r in body["loops"])
