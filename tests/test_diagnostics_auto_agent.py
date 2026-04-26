"""GET /api/diagnostics/auto-agent endpoint (spec §6.2)."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from unittest.mock import MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router
from preflight.audit import PreflightAuditEntry, PreflightAuditStore


@pytest.fixture
def config(tmp_path: Path) -> MagicMock:
    cfg = MagicMock()
    cfg.data_root = tmp_path
    cfg.data_path = lambda *parts: tmp_path.joinpath(*parts)  # noqa: PLW0108
    cfg.factory_metrics_path = tmp_path / "diagnostics" / "factory_metrics.jsonl"
    cfg.repo = "o/r"
    return cfg


@pytest.fixture
def client(config: MagicMock) -> TestClient:
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    return TestClient(app)


def _make_entry(
    tmp_path: Path,
    *,
    cost_usd: float,
    status: str = "resolved",
    issue: int = 1,
    sub_label: str = "x",
) -> PreflightAuditEntry:
    now = datetime.now(UTC).isoformat().replace("+00:00", "Z")
    return PreflightAuditEntry(
        ts=now,
        issue=issue,
        sub_label=sub_label,
        attempt_n=1,
        prompt_hash="h",
        cost_usd=cost_usd,
        wall_clock_s=10.0,
        tokens=100,
        status=status,
        pr_url=None,
        diagnosis="d",
        llm_summary="s",
    )


def test_route_registered(client: TestClient) -> None:
    """Endpoint must be mounted; a 404 means the UI has no data source."""
    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code != 404, (
        "/api/diagnostics/auto-agent not mounted on the diagnostics router"
    )


def test_returns_24h_and_7d_stats(tmp_path: Path, config: MagicMock) -> None:
    """Endpoint returns aggregated payload with today + last_7d + top_spend."""
    store = PreflightAuditStore(tmp_path)
    for cost in [1.0, 2.0]:
        store.append(_make_entry(tmp_path, cost_usd=cost))

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    client = TestClient(app)

    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code == 200

    body = response.json()
    assert "today" in body
    assert "last_7d" in body
    assert "top_spend" in body

    today = body["today"]
    assert today["attempts"] == 2
    assert today["spend_usd"] == pytest.approx(3.0)
    assert today["resolved"] == 2
    assert today["resolution_rate"] == pytest.approx(1.0)

    last_7d = body["last_7d"]
    assert last_7d["attempts"] == 2
    assert last_7d["spend_usd"] == pytest.approx(3.0)


def test_top_spend_sorted_desc(tmp_path: Path, config: MagicMock) -> None:
    """top_spend list is sorted highest-cost first, capped at 5."""
    store = PreflightAuditStore(tmp_path)
    costs = [5.0, 1.0, 3.0, 4.0, 2.0]
    for i, cost in enumerate(costs):
        store.append(_make_entry(tmp_path, cost_usd=cost, issue=i + 1))

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    client = TestClient(app)

    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code == 200

    top = response.json()["top_spend"]
    assert len(top) == 5
    returned_costs = [e["cost_usd"] for e in top]
    assert returned_costs == sorted(returned_costs, reverse=True)


def test_top_spend_entry_shape(tmp_path: Path, config: MagicMock) -> None:
    """Each top_spend entry has all required fields."""
    store = PreflightAuditStore(tmp_path)
    store.append(_make_entry(tmp_path, cost_usd=1.5, issue=7, sub_label="bug"))

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    client = TestClient(app)

    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code == 200

    entry = response.json()["top_spend"][0]
    for field in ("issue", "sub_label", "cost_usd", "wall_clock_s", "status", "ts"):
        assert field in entry, f"missing field: {field}"
    assert entry["issue"] == 7
    assert entry["sub_label"] == "bug"
    assert entry["cost_usd"] == pytest.approx(1.5)


def test_stats_payload_shape(client: TestClient) -> None:
    """Both today and last_7d have the full §6.2 stats shape (empty store)."""
    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code == 200
    body = response.json()
    for key in ("today", "last_7d"):
        section = body[key]
        for field in (
            "spend_usd",
            "attempts",
            "resolved",
            "resolution_rate",
            "p50_cost_usd",
            "p95_cost_usd",
            "p50_wall_clock_s",
            "p95_wall_clock_s",
        ):
            assert field in section, f"{key} missing field: {field}"


def test_empty_store_returns_zeros(client: TestClient) -> None:
    """With no audit data, all stats are zero and top_spend is empty."""
    response = client.get("/api/diagnostics/auto-agent")
    assert response.status_code == 200
    body = response.json()
    assert body["today"]["attempts"] == 0
    assert body["today"]["spend_usd"] == 0.0
    assert body["top_spend"] == []
