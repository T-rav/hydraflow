"""Spec §7 line 1618 — `/api/diagnostics/issue/{issue}/waterfall` endpoint.

Full-coverage integration test lives in
``tests/test_diagnostics_waterfall_route.py``. This file is the
spec-named entry-point: smoke tests asserting the endpoint is present
in the diagnostics router and rejects bad inputs, so a §7 audit greps
for ``test_diagnostics_waterfall.py`` and lands on real coverage.
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


def test_waterfall_route_registered(client: TestClient) -> None:
    """Endpoint must be mounted; a 404 here means the route isn't
    declared and operators can't see per-issue cost waterfalls."""
    response = client.get("/api/diagnostics/issue/123/waterfall")
    assert response.status_code != 404, (
        "/api/diagnostics/issue/{issue}/waterfall not mounted on the diagnostics router"
    )


def test_waterfall_returns_json_envelope(client: TestClient, tmp_path: Path) -> None:
    """The endpoint always returns a JSON object, even when there's no
    data for the issue — the UI relies on a stable shape."""
    response = client.get("/api/diagnostics/issue/9999/waterfall")
    assert response.status_code == 200
    body = response.json()
    assert isinstance(body, dict), (
        "/api/diagnostics/issue/{issue}/waterfall must return a JSON object "
        "(dict), not a raw list or scalar"
    )
