"""Control-plane auth, minting, revocation, and lifespan tests."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

import hydraflow_gateway.__main__ as gateway_entrypoint
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import MintKeyRequest, ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from mockworld.fakes.fake_clock import FakeClock

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"


def _settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://upstream.test",
                api_key=SecretStr("provider-secret"),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
        body_capture_repo_slugs=frozenset({"acme/hydraflow"}),
        max_key_ttl_seconds=300,
        reaper_interval_seconds=1,
    )


def _mint_body(**overrides: object) -> dict[str, object]:
    body: dict[str, object] = {
        "principal_kind": "spawn",
        "principal_id": "implementer",
        "spawn_id": "spawn-1",
        "session_id": "session-1",
        "repo_slug": "acme/hydraflow",
        "repo_class": "hydraflow",
        "provider_binding": "anthropic",
        "capture_bodies": False,
        "ttl_seconds": 60,
    }
    body.update(overrides)
    return body


def _client(
    tmp_path: Path,
    *,
    store: VirtualKeyStore | None = None,
    sleep: object | None = None,
) -> tuple[httpx.AsyncClient, object]:
    settings = _settings(tmp_path)

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
    kwargs: dict[str, object] = {}
    if sleep is not None:
        kwargs["sleep"] = sleep
    app = create_app(
        settings,
        key_store=store,
        client=upstream_client,
        **kwargs,
    )
    return (
        httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url="http://gateway.test",
        ),
        app,
    )


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        if False:
            yield b""


class TestGatewayControlPlane:
    async def test_health_is_public_and_reports_configured_provider(
        self, tmp_path: Path
    ) -> None:
        client, _ = _client(tmp_path)
        try:
            response = await client.get("/healthz")
        finally:
            await client.aclose()

        assert response.status_code == 200
        assert response.json() == {"status": "ok", "providers": ["anthropic"]}

    async def test_mint_requires_distinct_control_bearer(self, tmp_path: Path) -> None:
        client, _ = _client(tmp_path)
        try:
            missing = await client.post("/control/v1/keys", json=_mint_body())
            wrong = await client.post(
                "/control/v1/keys",
                headers={"authorization": "Bearer wrong-secret"},
                json=_mint_body(),
            )
        finally:
            await client.aclose()

        assert missing.status_code == 401
        assert wrong.status_code == 401
        assert _CONTROL_TOKEN not in missing.text + wrong.text

    async def test_control_auth_and_size_bound_run_before_json_parsing(
        self, tmp_path: Path
    ) -> None:
        client, _ = _client(tmp_path)

        async def oversized_chunks() -> AsyncIterator[bytes]:
            for _ in range(5):
                yield b"x" * 4096

        try:
            unauthorized = await client.post(
                "/control/v1/keys",
                headers={"authorization": "Bearer wrong-secret"},
                content=b"{" + (b"x" * 20_000),
            )
            oversized = await client.post(
                "/control/v1/keys",
                headers={"authorization": f"Bearer {_CONTROL_TOKEN}"},
                content=oversized_chunks(),
            )
        finally:
            await client.aclose()

        assert unauthorized.status_code == 401
        assert oversized.status_code == 413
        assert oversized.json() == {"detail": "control request body is too large"}

    async def test_mint_returns_wire_contract_and_revoke_invalidates_token(
        self, tmp_path: Path
    ) -> None:
        client, _ = _client(tmp_path)
        control_headers = {"authorization": f"Bearer {_CONTROL_TOKEN}"}
        try:
            minted = await client.post(
                "/control/v1/keys",
                headers=control_headers,
                json=_mint_body(),
            )
            payload = minted.json()
            before_revoke = await client.get(
                "/v1/models", headers={"x-api-key": payload["token"]}
            )
            revoked = await client.delete(
                f"/control/v1/keys/{payload['key_id']}", headers=control_headers
            )
            after_revoke = await client.get(
                "/v1/models", headers={"x-api-key": payload["token"]}
            )
        finally:
            await client.aclose()

        assert minted.status_code == 201
        assert set(payload) == {"key_id", "token", "expires_at"}
        assert payload["token"].startswith("hfgw_")
        assert before_revoke.status_code == 200
        assert revoked.json() == {"key_id": payload["key_id"], "revoked": True}
        assert after_revoke.status_code == 401

    async def test_mint_rejects_unavailable_provider_ttl_and_capture_policy(
        self, tmp_path: Path
    ) -> None:
        client, _ = _client(tmp_path)
        headers = {"authorization": f"Bearer {_CONTROL_TOKEN}"}
        try:
            unavailable = await client.post(
                "/control/v1/keys",
                headers=headers,
                json=_mint_body(provider_binding="zai-harness"),
            )
            oversized_ttl = await client.post(
                "/control/v1/keys",
                headers=headers,
                json=_mint_body(ttl_seconds=301),
            )
            client_capture = await client.post(
                "/control/v1/keys",
                headers=headers,
                json=_mint_body(repo_class="client", capture_bodies=True),
            )
            spoofed_hydraflow_capture = await client.post(
                "/control/v1/keys",
                headers=headers,
                json=_mint_body(
                    repo_slug="client/private",
                    repo_class="hydraflow",
                    capture_bodies=True,
                ),
            )
            approved_capture = await client.post(
                "/control/v1/keys",
                headers=headers,
                json=_mint_body(capture_bodies=True),
            )
        finally:
            await client.aclose()

        assert unavailable.status_code == 422
        assert oversized_ttl.status_code == 422
        assert client_capture.status_code == 422
        assert spoofed_hydraflow_capture.status_code == 422
        assert approved_capture.status_code == 201


class TestGatewayLifespan:
    async def test_reaper_removes_expired_keys_and_shuts_down_cleanly(
        self, tmp_path: Path
    ) -> None:
        clock = FakeClock()
        store = VirtualKeyStore(
            max_ttl_seconds=60,
            wall_clock=clock.now,
            monotonic=clock.monotonic,
        )
        store.mint(MintKeyRequest.model_validate(_mint_body(ttl_seconds=1)))
        reaped = asyncio.Event()
        block = asyncio.Event()
        sleep_calls = 0

        async def controlled_sleep(_: float) -> None:
            nonlocal sleep_calls
            sleep_calls += 1
            if sleep_calls == 1:
                clock.advance(1)
                return
            reaped.set()
            await block.wait()

        client, app = _client(tmp_path, store=store, sleep=controlled_sleep)
        try:
            async with app.router.lifespan_context(app):
                await asyncio.wait_for(reaped.wait(), timeout=1)
                assert store.active_count == 0
        finally:
            await client.aclose()


def test_gateway_entrypoint_disables_query_bearing_access_logs(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    captured: dict[str, object] = {}

    def fake_run(*args: object, **kwargs: object) -> None:
        captured["args"] = args
        captured.update(kwargs)

    monkeypatch.setattr(gateway_entrypoint.uvicorn, "run", fake_run)

    gateway_entrypoint.main()

    assert captured["access_log"] is False
    assert captured["date_header"] is False
    assert captured["server_header"] is False
    assert captured["workers"] == 1
