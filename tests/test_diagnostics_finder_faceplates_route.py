"""Tests for GET /api/diagnostics/finder-faceplates (#10826).

Read-only panel: an empty ledger yields every finder pending (never a 500);
a populated ledger surfaces the measured floor; the live finding-rate is wired
finder→loop from the per-loop rollup and drives the status.
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

import dashboard_routes._diagnostics_routes as diag  # noqa: E402
from dashboard_routes._diagnostics_routes import build_diagnostics_router  # noqa: E402
from finder_calibration import (  # noqa: E402
    CalibrationLedger,
    FinderFloor,
    calibration_ledger_path,
)
from finder_faceplate import (  # noqa: E402
    FINDER_LOOP_WORKER,
    BaselineLedger,
    BaselineProvenance,
    baseline_ledger_path,
)

_NOW = datetime(2026, 8, 3, 12, 0, 0, tzinfo=UTC)


def _config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.repo = "o/r"
    return cfg


def _client(cfg: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(cfg))
    return TestClient(app)


def _record_wiki_rot_floor(
    tmp_path: Path, *, vetted_at: datetime | None = _NOW
) -> None:
    CalibrationLedger(calibration_ledger_path(tmp_path)).record(
        FinderFloor(
            finder_id="wiki_rot",
            floor_mean=1.0,
            floor_sigma=0.0,
            sample_count=3,
            threshold=1,
            last_calibrated=_NOW,
        )
    )
    BaselineLedger(baseline_ledger_path(tmp_path)).record(
        BaselineProvenance(
            finder_id="wiki_rot",
            sha="cafef00d",
            vetted_by="operator-supplied",
            signal_class="wiki-rot",
            vetted_at=vetted_at,
        )
    )


def test_empty_ledger_returns_all_pending(tmp_path: Path) -> None:
    resp = _client(_config(tmp_path)).get("/api/diagnostics/finder-faceplates")
    assert resp.status_code == 200
    body = resp.json()
    finders = body["finders"]
    assert len(finders) == len(FINDER_LOOP_WORKER)
    assert all(row["calibrated"] is False for row in finders)
    assert all(row["status"] == "uncalibrated" for row in finders)


def test_populated_ledger_surfaces_floor(tmp_path: Path, monkeypatch) -> None:
    _record_wiki_rot_floor(tmp_path)
    # No live telemetry → live_rate null, status within_floor (documented).
    monkeypatch.setattr(diag, "build_per_loop_cost", lambda *a, **k: [])

    resp = _client(_config(tmp_path)).get("/api/diagnostics/finder-faceplates")
    assert resp.status_code == 200
    rows = {r["finder_id"]: r for r in resp.json()["finders"]}

    wiki = rows["wiki_rot"]
    assert wiki["calibrated"] is True
    assert wiki["floor_mean"] == 1.0
    assert wiki["threshold"] == 1
    assert wiki["sample_count"] == 3
    assert wiki["low_confidence"] is False
    assert wiki["baseline_vetted"] is True
    assert wiki["baseline_stale"] is False
    assert wiki["live_rate"] is None
    assert wiki["status"] == "within_floor"
    # Uncalibrated finders still appear as pending rows.
    assert rows["term_proposer"]["calibrated"] is False


def test_live_rate_wired_finder_to_loop_drives_status(
    tmp_path: Path, monkeypatch
) -> None:
    _record_wiki_rot_floor(tmp_path)
    # wiki_rot's loop filed 9 findings recently — above the floor threshold of 1.
    monkeypatch.setattr(
        diag,
        "build_per_loop_cost",
        lambda *a, **k: [{"loop": "wiki_rot_detector", "issues_filed": 9}],
    )

    resp = _client(_config(tmp_path)).get("/api/diagnostics/finder-faceplates")
    rows = {r["finder_id"]: r for r in resp.json()["finders"]}

    assert rows["wiki_rot"]["live_rate"] == 9
    assert rows["wiki_rot"]["status"] == "above_floor"


def test_unvouched_baseline_flags_low_confidence_over_route(
    tmp_path: Path, monkeypatch
) -> None:
    _record_wiki_rot_floor(tmp_path, vetted_at=None)
    monkeypatch.setattr(diag, "build_per_loop_cost", lambda *a, **k: [])

    resp = _client(_config(tmp_path)).get("/api/diagnostics/finder-faceplates")
    wiki = next(r for r in resp.json()["finders"] if r["finder_id"] == "wiki_rot")

    assert wiki["baseline_vetted"] is False
    assert wiki["low_confidence"] is True
    assert wiki["baseline_stale"] is None


def test_live_rate_rollup_failure_is_soft(tmp_path: Path, monkeypatch) -> None:
    _record_wiki_rot_floor(tmp_path)

    def boom(*_a, **_k):
        raise RuntimeError("rollup exploded")

    monkeypatch.setattr(diag, "build_per_loop_cost", boom)

    resp = _client(_config(tmp_path)).get("/api/diagnostics/finder-faceplates")
    # A rollup failure must degrade to null live rates, never 500 the panel.
    assert resp.status_code == 200
    wiki = next(r for r in resp.json()["finders"] if r["finder_id"] == "wiki_rot")
    assert wiki["live_rate"] is None


@pytest.mark.parametrize("window", ["24h", "7d", "30d", "all"])
def test_accepts_range_param(tmp_path: Path, monkeypatch, window: str) -> None:
    monkeypatch.setattr(diag, "build_per_loop_cost", lambda *a, **k: [])
    resp = _client(_config(tmp_path)).get(
        f"/api/diagnostics/finder-faceplates?range={window}"
    )
    assert resp.status_code == 200
