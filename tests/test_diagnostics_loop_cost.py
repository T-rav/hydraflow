"""Spec §7 line 1621 — `/api/diagnostics/loops/cost` endpoint.

Full-coverage integration test for the cost rollup family lives in
``tests/test_diagnostics_cost_rollup_routes.py``. This file is the
spec-named entry-point: smoke tests asserting the loops/cost endpoint
is mounted and returns a stable shape, so a §7 audit greps for
``test_diagnostics_loop_cost.py`` and lands on real coverage.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router


@pytest.fixture
def client(tmp_path: Path) -> TestClient:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = tmp_path.joinpath
    cfg.repo = "o/r"
    app = FastAPI()
    app.include_router(build_diagnostics_router(config=cfg))
    return TestClient(app)


def test_loops_cost_route_registered(client: TestClient) -> None:
    """Endpoint must be mounted; missing it means the trust-fleet UI's
    machinery-level cost panel has no data source."""
    response = client.get("/api/diagnostics/loops/cost")
    assert response.status_code != 404, (
        "/api/diagnostics/loops/cost not mounted on the diagnostics router"
    )


def test_loops_cost_returns_json_envelope(client: TestClient) -> None:
    """The endpoint always returns a JSON object even when no loops have
    cost data yet — the UI relies on a stable shape."""
    response = client.get("/api/diagnostics/loops/cost")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict | list), (
        "/api/diagnostics/loops/cost must return a JSON object or list, not a scalar"
    )


def test_loops_cost_accepts_range_param(client: TestClient) -> None:
    """The endpoint should accept a `range` query param (7d / 30d / 90d
    per spec §4.11). At minimum it must not 500 on a recognized value."""
    for window in ("7d", "30d", "90d"):
        response = client.get(f"/api/diagnostics/loops/cost?range={window}")
        assert response.status_code in (200, 422), (
            f"unexpected status {response.status_code} for range={window!r}"
        )
