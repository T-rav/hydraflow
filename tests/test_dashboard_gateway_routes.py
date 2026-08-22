"""Dashboard proxy for the gateway's read-only account and route plane."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dashboard_routes._gateway_routes import build_gateway_router
from gateway_control_reader import (
    GatewayControlReader,
    GatewaySourceState,
    canonical_worker_role,
)
from hydraflow_gateway.active_routes import ActiveRouteRegistry
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayLedgerRow
from hydraflow_gateway.models import (
    GatewayRequestStatus,
    MintKeyRequest,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from tests.helpers import ConfigFactory

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        return
        yield b""

    async def aclose(self) -> None:
        return None


def _gateway_settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://zai.test/api/anthropic",
                api_key=SecretStr("real-zai-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _row(request_id: str) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal={
            "kind": "spawn",
            "id": "implementer",
            "spawn_id": "spawn-1",
            "issue_number": 11534,
        },
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="metadata-only",
        timestamp=_NOW,
        latency_ms=12.0,
        status_code=200,
        status=GatewayRequestStatus.COMPLETED,
        upstream_provider=ProviderBinding.ZAI_HARNESS,
        path="/v1/messages",
        model_requested="glm-5.2",
        model_served="glm-5.3",
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.25,
        cost_unknown=False,
    )


def _live_gateway(tmp_path: Path, *, principal_id: str = "implementer") -> FastAPI:
    """Build a real gateway app with one lease, one in-flight, one terminal route."""
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id=principal_id,
            spawn_id="spawn-1",
            session_id="session-1",
            issue_number=11534,
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ZAI_HARNESS,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    identity = store.resolve(minted.token)
    registry = ActiveRouteRegistry(started_at=_NOW)
    registry.register(
        request_id="req-live", identity=identity, path="/v1/messages", started_at=_NOW
    )
    registry.register(
        request_id="req-done", identity=identity, path="/v1/messages", started_at=_NOW
    )
    registry.release(_row("req-done"))

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    return create_app(
        _gateway_settings(tmp_path),
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=registry,
        wall_clock=_NOW.timestamp,
    )


def _dashboard(
    tmp_path: Path,
    *,
    gateway: FastAPI | None = None,
    control_token: str = _CONTROL_TOKEN,
    unreachable: bool = False,
    principal_id: str = "implementer",
) -> TestClient:
    config = ConfigFactory.create()
    resolved = gateway or _live_gateway(tmp_path, principal_id=principal_id)

    def client_factory() -> httpx.AsyncClient:
        if unreachable:

            async def dead(_: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("gateway down")

            return httpx.AsyncClient(transport=httpx.MockTransport(dead))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=resolved))

    def reader_factory() -> GatewayControlReader:
        return GatewayControlReader(
            base_url="http://gateway.test",
            control_token=control_token,
            client_factory=client_factory,
        )

    app = FastAPI()
    app.include_router(build_gateway_router(config, reader_factory=reader_factory))
    return TestClient(app)


def test_accounts_route_returns_the_gateway_account_inventory(tmp_path: Path) -> None:
    """The dashboard surfaces the gateway's compiled account identities."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").json()

    assert [account["account_id"] for account in body["data"]["accounts"]] == [
        "legacy-anthropic",
        "legacy-zai-harness",
    ]


def test_accounts_route_marks_an_available_source(tmp_path: Path) -> None:
    """A successful read is explicitly labelled available."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").json()

    assert body["available"] is True


def test_accounts_route_forwards_the_requested_window(tmp_path: Path) -> None:
    """The operator's window reaches the gateway rather than being ignored."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts?window_seconds=600").json()

    assert body["data"]["window_seconds"] == 600


def test_accounts_route_rejects_an_out_of_range_window(tmp_path: Path) -> None:
    """The proxy bounds its own inputs; it does not relay arbitrary queries."""
    response = _dashboard(tmp_path).get("/api/gateway/accounts?window_seconds=0")

    assert response.status_code == 422


def _dig(payload: object, keys: tuple[str | int, ...]) -> object:
    """Walk a nested JSON payload by key/index path."""
    current = payload
    for key in keys:
        current = current[key]  # type: ignore[index]
    return current


@pytest.mark.parametrize(
    ("endpoint", "keys", "expected"),
    [
        pytest.param(
            "/api/gateway/routes/active",
            ("leases", 0, "account_id"),
            "legacy-zai-harness",
            id="a-minted-key-is-a-lease-on-its-bound-account",
        ),
        pytest.param(
            "/api/gateway/routes/active",
            ("in_flight", 0, "request_id"),
            "req-live",
            id="a-streaming-request-is-reported-separately-from-leases",
        ),
        pytest.param(
            "/api/gateway/routes/active",
            ("in_flight", 0, "worker_role"),
            "implementer",
            id="a-catalog-principal-gets-the-adr-0137-role-join",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "model_requested"),
            "glm-5.2",
            id="a-terminal-route-keeps-the-requested-model",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "model_served"),
            "glm-5.3",
            id="a-terminal-route-keeps-the-served-model",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "status"),
            "completed",
            id="a-terminal-route-keeps-its-status",
        ),
    ],
)
def test_live_view_column_is_proxied_through_unchanged(
    tmp_path: Path, endpoint: str, keys: tuple[str | int, ...], expected: object
) -> None:
    """Each column the Live view reads reaches the dashboard from the gateway."""
    body = _dashboard(tmp_path).get(endpoint).json()

    assert _dig(body["data"], keys) == expected


def test_active_routes_leave_an_unmapped_principal_unroled(tmp_path: Path) -> None:
    """A loop name is not a worker role, and is never guessed into one."""
    client = _dashboard(tmp_path, principal_id="adr_review")
    body = client.get("/api/gateway/routes/active").json()

    assert body["data"]["in_flight"][0]["worker_role"] is None


def test_recent_routes_rejects_an_unbounded_limit(tmp_path: Path) -> None:
    """A page size ceiling keeps a dashboard poll from becoming a scan."""
    response = _dashboard(tmp_path).get("/api/gateway/routes/recent?limit=100000")

    assert response.status_code == 422


def test_missing_control_token_reports_a_not_configured_source(
    tmp_path: Path,
) -> None:
    """Without the env-only credential the view says so; it does not look empty."""
    body = _dashboard(tmp_path, control_token="").get("/api/gateway/accounts").json()

    assert body["source_state"] == GatewaySourceState.NOT_CONFIGURED.value


def test_missing_control_token_returns_no_fabricated_data(tmp_path: Path) -> None:
    """An unavailable source must never present an invented account list."""
    body = _dashboard(tmp_path, control_token="").get("/api/gateway/accounts").json()

    assert body["data"] is None


def test_unreachable_gateway_reports_an_unreachable_source(tmp_path: Path) -> None:
    """A gateway that cannot be reached is distinguishable from a quiet one."""
    body = _dashboard(tmp_path, unreachable=True).get("/api/gateway/accounts").json()

    assert body["source_state"] == GatewaySourceState.UNREACHABLE.value


def test_unreachable_gateway_still_answers_with_2xx(tmp_path: Path) -> None:
    """The panel renders a degraded state rather than a browser-level error."""
    response = _dashboard(tmp_path, unreachable=True).get("/api/gateway/accounts")

    assert response.status_code == 200


def test_dashboard_response_never_carries_the_control_token(tmp_path: Path) -> None:
    """The browser must not be able to read the gateway control credential."""
    body = _dashboard(tmp_path).get("/api/gateway/routes/active").text

    assert _CONTROL_TOKEN not in body


def test_dashboard_response_never_carries_an_upstream_provider_key(
    tmp_path: Path,
) -> None:
    """No provider secret crosses the proxy boundary."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").text

    assert "real-zai-key" not in body


@pytest.mark.parametrize(
    ("principal_id", "expected"),
    [
        ("implementer", "implementer"),
        ("REVIEWER", "reviewer"),
        (" planner ", "planner"),
        ("issue_controller", None),
        ("", None),
    ],
)
def test_canonical_worker_role_matches_exactly(
    principal_id: str, expected: str | None
) -> None:
    """The role join is an exact catalog match, never a heuristic."""
    assert canonical_worker_role(principal_id) == expected
