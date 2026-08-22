"""Authenticated read APIs for accounts and active/recent routes (ADR-0138)."""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

from hydraflow_gateway.active_routes import ActiveRouteRegistry
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding, RepoClass
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


async def test_data_plane_passthrough_still_owns_unknown_paths(
    tmp_path: Path,
) -> None:
    """The v2 reads must not shadow the catch-all data plane."""
    async with _client(tmp_path) as client:
        response = await client.get("/v1/models")

    assert response.status_code == 401
