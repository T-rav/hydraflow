"""Authenticated read APIs for accounts and active/recent routes (ADR-0138)."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

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

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_CONTROL_TOKEN}"}


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        return
        yield b""

    async def aclose(self) -> None:
        return None


def _settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test/prefix",
                api_key=SecretStr("real-anthropic-key"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _mint(store: VirtualKeyStore) -> None:
    store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id="implementer",
            spawn_id="spawn-1",
            session_id="session-1",
            issue_number=11534,
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ANTHROPIC,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )


def _client(
    tmp_path: Path,
    *,
    store: VirtualKeyStore | None = None,
    registry: ActiveRouteRegistry | None = None,
) -> httpx.AsyncClient:
    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    app = create_app(
        _settings(tmp_path),
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=registry,
        wall_clock=_NOW.timestamp,
    )
    return httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app),
        base_url="http://gateway.test",
    )


@pytest.mark.parametrize(
    "path",
    ["/control/v2/accounts", "/control/v2/routes/active", "/control/v2/routes/recent"],
)
async def test_read_apis_reject_an_unauthenticated_caller(
    tmp_path: Path, path: str
) -> None:
    """The v2 read plane sits behind the same control boundary as v1."""
    async with _client(tmp_path) as client:
        response = await client.get(path)

    assert response.status_code == 401


async def test_accounts_endpoint_lists_every_compiled_account(
    tmp_path: Path,
) -> None:
    """Both legacy bindings appear, configured or not."""
    async with _client(tmp_path) as client:
        response = await client.get("/control/v2/accounts", headers=_AUTH)

    assert [account["account_id"] for account in response.json()["accounts"]] == [
        "legacy-anthropic",
        "legacy-zai-harness",
    ]


async def test_accounts_endpoint_reports_a_live_lease(tmp_path: Path) -> None:
    """A minted key is visible as a lease on its bound account."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    _mint(store)

    async with _client(tmp_path, store=store) as client:
        response = await client.get("/control/v2/accounts", headers=_AUTH)

    accounts = {a["account_id"]: a for a in response.json()["accounts"]}
    assert accounts["legacy-anthropic"]["lease_count"] == 1


async def test_accounts_endpoint_bounds_the_evidence_window(tmp_path: Path) -> None:
    """An out-of-range window is rejected rather than silently clamped."""
    async with _client(tmp_path) as client:
        response = await client.get(
            "/control/v2/accounts?window_seconds=999999", headers=_AUTH
        )

    assert response.status_code == 422


async def test_accounts_endpoint_honours_a_valid_window(tmp_path: Path) -> None:
    """The window the caller asked for is the window the payload publishes."""
    async with _client(tmp_path) as client:
        response = await client.get(
            "/control/v2/accounts?window_seconds=600", headers=_AUTH
        )

    assert response.json()["window_seconds"] == 600


async def test_active_routes_endpoint_lists_leases(tmp_path: Path) -> None:
    """The Live view reads leases from the key store, not from a guess."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    _mint(store)

    async with _client(tmp_path, store=store) as client:
        response = await client.get("/control/v2/routes/active", headers=_AUTH)

    assert len(response.json()["leases"]) == 1


async def test_active_routes_lease_carries_its_issue_attribution(
    tmp_path: Path,
) -> None:
    """Issue attribution threaded through mint reaches the operator view."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    _mint(store)

    async with _client(tmp_path, store=store) as client:
        response = await client.get("/control/v2/routes/active", headers=_AUTH)

    assert response.json()["leases"][0]["issue_number"] == 11534


async def test_active_routes_endpoint_is_empty_without_traffic(
    tmp_path: Path,
) -> None:
    """No request means no in-flight row, even when a lease exists."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    _mint(store)

    async with _client(tmp_path, store=store) as client:
        response = await client.get("/control/v2/routes/active", headers=_AUTH)

    assert response.json()["in_flight"] == []


async def test_recent_routes_endpoint_bounds_its_limit(tmp_path: Path) -> None:
    """An unbounded page size would turn a read into a scan."""
    async with _client(tmp_path) as client:
        response = await client.get(
            "/control/v2/routes/recent?limit=100000", headers=_AUTH
        )

    assert response.status_code == 422


async def test_recent_routes_endpoint_publishes_its_capacity(
    tmp_path: Path,
) -> None:
    """The view states the bound it was computed under."""
    async with _client(tmp_path, registry=ActiveRouteRegistry(recent_capacity=5)) as (
        client
    ):
        response = await client.get("/control/v2/routes/recent", headers=_AUTH)

    assert response.json()["capacity"] == 5


async def test_recent_routes_endpoint_publishes_when_it_began_observing(
    tmp_path: Path,
) -> None:
    """Process-local evidence must say when it started, so it cannot overclaim."""
    registry = ActiveRouteRegistry(started_at=_NOW)

    async with _client(tmp_path, registry=registry) as client:
        response = await client.get("/control/v2/routes/recent", headers=_AUTH)

    assert response.json()["evidence_since"].startswith("2026-08-22T12:00:00")


def _drained(registry: ActiveRouteRegistry, count: int) -> ActiveRouteRegistry:
    """Register and finalize *count* routes so the recent ring holds them."""
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-drain")
    _mint(store)
    identity = store.lease_identities()[0]
    for index in range(count):
        request_id = f"req-{index}"
        registry.register(
            request_id=request_id,
            identity=identity,
            path="/v1/messages",
            started_at=_NOW,
        )
        registry.release(
            GatewayLedgerRow(
                request_id=request_id,
                key_id=identity.key_id,
                principal=identity.principal,
                repo_slug=identity.repo_slug,
                repo_class=identity.repo_class,
                body_capture_policy=identity.body_capture_policy,
                timestamp=_NOW,
                latency_ms=1.0,
                status_code=200,
                status=GatewayRequestStatus.COMPLETED,
                upstream_provider=identity.provider_binding,
                path="/v1/messages",
                completed=True,
                client_aborted=False,
                usage_complete=True,
                cost_usd=0.0,
                cost_unknown=False,
            )
        )
    return registry


async def test_recent_routes_declares_a_page_that_hid_rows(tmp_path: Path) -> None:
    """A bounded page must not report itself as a complete view."""
    registry = _drained(ActiveRouteRegistry(started_at=_NOW), 5)

    async with _client(tmp_path, registry=registry) as client:
        response = await client.get("/control/v2/routes/recent?limit=2", headers=_AUTH)

    assert response.json()["truncated"] is True


async def test_recent_routes_publishes_what_the_ring_retains(tmp_path: Path) -> None:
    """`retained` versus the returned page is what makes truncation checkable."""
    registry = _drained(ActiveRouteRegistry(started_at=_NOW), 5)

    async with _client(tmp_path, registry=registry) as client:
        response = await client.get("/control/v2/routes/recent?limit=2", headers=_AUTH)

    assert response.json()["retained"] == 5


async def test_a_complete_page_is_not_reported_as_truncated(tmp_path: Path) -> None:
    """Truncation must stay a real signal, not a permanent warning."""
    registry = _drained(ActiveRouteRegistry(started_at=_NOW), 2)

    async with _client(tmp_path, registry=registry) as client:
        response = await client.get("/control/v2/routes/recent?limit=50", headers=_AUTH)

    assert response.json()["truncated"] is False


async def test_accounts_declare_evidence_evicted_by_the_ring(tmp_path: Path) -> None:
    """Health over an evicted window is a subsample, and the view says so."""
    registry = _drained(ActiveRouteRegistry(started_at=_NOW, recent_capacity=2), 4)

    async with _client(tmp_path, registry=registry) as client:
        response = await client.get("/control/v2/accounts", headers=_AUTH)

    assert response.json()["evidence_truncated"] is True


async def test_shutdown_clears_every_in_flight_route(tmp_path: Path) -> None:
    """The lifespan's terminal event is wired, not merely available on the registry."""
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
    _mint(store)
    registry = ActiveRouteRegistry(started_at=_NOW)
    blocked = asyncio.Event()

    async def never(_: float) -> None:
        await blocked.wait()

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    app = create_app(
        _settings(tmp_path),
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=registry,
        sleep=never,
        wall_clock=_NOW.timestamp,
    )
    async with app.router.lifespan_context(app):
        registry.register(
            request_id="req-live",
            identity=store.lease_identities()[0],
            path="/v1/messages",
            started_at=_NOW,
        )

    assert registry.in_flight() == ()


async def test_data_plane_passthrough_still_owns_unknown_paths(
    tmp_path: Path,
) -> None:
    """The v2 reads must not shadow the catch-all data plane."""
    async with _client(tmp_path) as client:
        response = await client.get("/v1/models")

    assert response.status_code == 401
