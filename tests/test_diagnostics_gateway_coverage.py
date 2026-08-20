"""Diagnostic API coverage for the global/repo gateway spend gauge."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path

from fastapi import FastAPI
from fastapi.testclient import TestClient

from dashboard_routes._diagnostics_routes import build_diagnostics_router
from gateway_coverage import gateway_coverage_snapshot_path, gateway_ledger_path
from route_types import REPO_ALL
from tests.conftest import make_state
from tests.helpers import (
    ConfigFactory,
    find_endpoint,
    make_dashboard_router,
    make_registry,
)

_NOW = datetime(2026, 8, 19, 20, tzinfo=UTC)


def _append(path: Path, row: dict[str, object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a", encoding="utf-8") as stream:
        stream.write(json.dumps(row) + "\n")


def _timestamp() -> str:
    return (_NOW - timedelta(hours=1)).isoformat()


def _gateway_row(repo_slug: str, cost_usd: float, request_id: str) -> dict[str, object]:
    return {
        "timestamp": _timestamp(),
        "request_id": request_id,
        "source": "gateway",
        "key_id": f"key-{request_id}",
        "principal": {
            "kind": "spawn",
            "id": "diagnostics-test",
            "spawn_id": f"spawn-{request_id}",
        },
        "repo_slug": repo_slug,
        "repo_class": "hydraflow",
        "body_capture_policy": "metadata-only",
        "latency_ms": 1.0,
        "status_code": 200,
        "status": "completed",
        "upstream_provider": "anthropic",
        "input_tokens": 1,
        "output_tokens": 1,
        "cache_read_input_tokens": 0,
        "cache_creation_input_tokens": 0,
        "completed": True,
        "client_aborted": False,
        "observer_malformed_events": 0,
        "cost_usd": cost_usd,
        "cost_unknown": False,
    }


def _config(tmp_path: Path, name: str, *, data_root: Path | None = None):
    repo_root = tmp_path / name / "repo"
    repo_root.mkdir(parents=True)
    config = ConfigFactory.create(
        repo_root=repo_root,
        repo=f"org/{name}",
    )
    object.__setattr__(config, "data_root", data_root or tmp_path / name / "data")
    return config


def test_gateway_coverage_endpoint_reports_complete_repo_gauge(
    tmp_path: Path, monkeypatch
) -> None:
    config = _config(tmp_path, "repo")
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: _NOW)
    _append(
        gateway_ledger_path(config),
        _gateway_row(config.repo_slug, 8.0, "req-1"),
    )
    snapshot_path = gateway_coverage_snapshot_path(config)
    snapshot_path.parent.mkdir(parents=True, exist_ok=True)
    snapshot_path.write_text(
        json.dumps({"ceiling_achieved": True, "regression_detected": True}),
        encoding="utf-8",
    )
    _append(
        config.cost_inferences_path,
        {
            "timestamp": _timestamp(),
            "repo_slug": "",
            "source": "wiki_compilation",
            "tool": "openrouter",
            "estimated_cost_usd": 2.0,
        },
    )

    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    body = TestClient(app).get("/api/diagnostics/gateway-coverage?range=24h")

    assert body.status_code == 200
    payload = body.json()
    assert payload["status"] == "complete"
    assert payload["scope"] == "repo"
    assert payload["coverage_percent"] == 80.0
    assert payload["bypassing_families"][0]["family"] == "wiki_compilation"
    assert payload["ceiling_achieved"] is True
    assert payload["regression_detected"] is True


def test_gateway_coverage_endpoint_scopes_repo_and_unions_global(
    tmp_path: Path, event_bus, state, config, monkeypatch
) -> None:
    shared_data = tmp_path / "shared-data"
    config_a = _config(tmp_path, "a", data_root=shared_data)
    config_b = _config(tmp_path, "b", data_root=shared_data)
    monkeypatch.setattr("dashboard_routes._cost_rollups._utcnow", lambda: _NOW)

    ledger = gateway_ledger_path(config_a)
    _append(ledger, _gateway_row("org-a", 8.0, "req-a"))
    _append(ledger, _gateway_row("org-b", 2.0, "req-b"))
    _append(
        config_a.cost_inferences_path,
        {
            "timestamp": _timestamp(),
            "source": "wiki_compilation",
            "tool": "openrouter",
            "estimated_cost_usd": 2.0,
        },
    )
    _append(
        config_b.cost_inferences_path,
        {
            "timestamp": _timestamp(),
            "source": "term_proposer",
            "tool": "kimi",
            "estimated_cost_usd": 8.0,
        },
    )

    registry = make_registry(
        {
            "slug": "org-a",
            "config": config_a,
            "state": make_state(tmp_path / "state-a"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
        {
            "slug": "org-b",
            "config": config_b,
            "state": make_state(tmp_path / "state-b"),
            "event_bus": event_bus,
            "orchestrator": None,
        },
    )
    router, _ = make_dashboard_router(
        config,
        event_bus,
        state,
        tmp_path,
        registry=registry,
        default_repo_slug="org-a",
    )
    endpoint = find_endpoint(router, "/api/diagnostics/gateway-coverage")

    global_payload = endpoint(range="24h", repo=REPO_ALL)
    repo_payload = endpoint(range="24h", repo="org-a")

    assert global_payload["scope"] == "global"
    assert global_payload["gateway_spend_usd"] == 10.0
    assert global_payload["bypass_spend_usd"] == 10.0
    assert global_payload["coverage_percent"] == 50.0
    assert {row["family"] for row in global_payload["bypassing_families"]} == {
        "wiki_compilation",
        "term_proposer",
    }
    assert repo_payload["scope"] == "repo"
    assert repo_payload["repo_slug"] == "org-a"
    assert repo_payload["coverage_percent"] == 80.0


def test_gateway_coverage_endpoint_rejects_unknown_range(tmp_path: Path) -> None:
    config = _config(tmp_path, "repo")
    app = FastAPI()
    app.include_router(build_diagnostics_router(config))
    response = TestClient(app).get("/api/diagnostics/gateway-coverage?range=forever")
    assert response.status_code == 400
