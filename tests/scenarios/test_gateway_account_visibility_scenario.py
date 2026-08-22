"""MockWorld scenario: account and active-route visibility across one real turn.

Everything on the observation path is real — the control plane, the harness
environment derivation, the streaming proxy, the active-route registry, the
gateway's v2 read endpoints, and HydraFlow's ``/api/gateway`` proxy routes. Only
the Claude subprocess and the external Anthropic origin are deterministic fakes.

The scenario proves the lifecycle an operator is being shown: the account is
idle before the turn, the request is visible *while it streams*, and the
in-flight row is gone once the turn finalizes — with the terminal route left as
recent evidence and no credential anywhere in the payloads.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Awaitable, Callable, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from pydantic import SecretStr

from dashboard_routes._gateway_routes import build_gateway_router
from execution import SimpleResult
from gateway_control_reader import GatewayControlReader
from gateway_coverage import gateway_ledger_path
from gateway_mint_client import GatewayMintCredential, GatewayMintRequest
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from runner_utils import _claude_cli_complete
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "scenario-control-token-0123456789abcdef"
_PROVIDER_KEY = "scenario-real-provider-key"
_SSE_BODY = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":11}}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","usage":'
    b'{"output_tokens":17}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _PausedStream(httpx.AsyncByteStream):
    """Upstream body that yields its head, waits for a probe, then completes."""

    def __init__(self, probed: Callable[[], Awaitable[None]]) -> None:
        self._probed = probed

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = len(_SSE_BODY) // 2
        yield _SSE_BODY[:midpoint]
        await self._probed()
        yield _SSE_BODY[midpoint:]


@dataclass(slots=True)
class _FakeAnthropicOrigin:
    """Deterministic external HTTP boundary that streams in two parts."""

    probed: Callable[[], Awaitable[None]]
    exchanges: list[str] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        await request.aread()
        self.exchanges.append(str(request.url))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_PausedStream(self.probed),
        )


@dataclass(slots=True)
class _InProcessGatewayControlClient:
    """Runner control adapter that drives the gateway's real mint endpoint."""

    client: httpx.AsyncClient

    async def mint_key(
        self,
        *,
        base_url: str,
        control_token: str,
        request: GatewayMintRequest,
    ) -> GatewayMintCredential:
        response = await self.client.post(
            f"{base_url.rstrip('/')}/control/v1/keys",
            headers={"authorization": f"Bearer {control_token}"},
            json=asdict(request),
        )
        response.raise_for_status()
        payload = response.json()
        return GatewayMintCredential(
            key_id=str(payload["key_id"]),
            token=str(payload["token"]),
            expires_at=str(payload["expires_at"]),
        )

    async def revoke_key(
        self, *, base_url: str, control_token: str, key_id: str
    ) -> bool:
        response = await self.client.delete(
            f"{base_url.rstrip('/')}/control/v1/keys/{key_id}",
            headers={"authorization": f"Bearer {control_token}"},
        )
        response.raise_for_status()
        return bool(response.json()["revoked"])


class _GatewayHarnessRunner:
    """Claude stand-in that performs one streaming API turn using its derived env."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client
        self.body = b""

    async def run_simple(
        self,
        _cmd: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> SimpleResult:
        worker_env = dict(env or {})
        async with self._client.stream(
            "POST",
            "/v1/messages",
            headers={
                "authorization": f"Bearer {worker_env['ANTHROPIC_AUTH_TOKEN']}",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": "claude-sonnet-4-6",
                "stream": True,
                "messages": [{"role": "user", "content": "scenario"}],
            },
        ) as response:
            response.raise_for_status()
            chunks = [chunk async for chunk in response.aiter_bytes()]
        self.body = b"".join(chunks)
        return SimpleResult(stdout="gateway session complete", returncode=0)


class TestGatewayAccountVisibilityScenario:
    """Idle account -> streaming request -> cleared in-flight -> recent evidence."""

    async def test_operator_sees_the_route_lifecycle_without_any_credential(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
        monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        ledger = GatewayLedger(gateway_ledger_path(config))
        key_store = VirtualKeyStore(
            max_ttl_seconds=config.gateway_key_ttl_seconds,
            id_factory=lambda: "scenario-key",
            secret_factory=lambda: "scenario-virtual-secret",
        )
        mid_stream: dict[str, Any] = {}

        async def probe() -> None:
            mid_stream.update(await _read(gateway_client, "/control/v2/routes/active"))

        origin = _FakeAnthropicOrigin(probed=probe)
        upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
        settings = GatewaySettings(
            control_token=SecretStr(_CONTROL_TOKEN),
            upstreams={
                ProviderBinding.ANTHROPIC: UpstreamSettings(
                    base_url="https://anthropic.test",
                    api_key=SecretStr(_PROVIDER_KEY),
                    auth_style=UpstreamAuthStyle.X_API_KEY,
                )
            },
            ledger_path=ledger.path,
            body_dir=config.data_root / "gateway" / "bodies",
            max_key_ttl_seconds=config.gateway_key_ttl_seconds,
        )
        app = create_app(
            settings,
            key_store=key_store,
            client=upstream_client,
            ledger=ledger,
            body_store=GatewayBodyStore(settings.body_dir),
        )
        gateway_client = httpx.AsyncClient(
            transport=httpx.ASGITransport(app=app),
            base_url=config.gateway_base_url,
        )
        runner = _GatewayHarnessRunner(gateway_client)

        try:
            idle = await _read(gateway_client, "/control/v2/accounts")

            result = await _claude_cli_complete(
                runner=runner,  # type: ignore[arg-type]
                tool="claude",
                model="claude-sonnet-4-6",
                prompt="Exercise one tool-using gateway turn.",
                timeout=10,
                gh_token="scenario-gh-token",
                isolate_user_settings=True,
                provider="gateway",
                config=config,
                source="implementer",
                session_id="scenario-session",
                gateway_client=_InProcessGatewayControlClient(gateway_client),
            )

            settled_accounts = await _read(gateway_client, "/control/v2/accounts")
            settled_routes = await _read(gateway_client, "/control/v2/routes/active")
            dashboard = _dashboard(config, app)
            recent = await _proxy_read(dashboard, "/api/gateway/routes/recent")
            accounts_body = await _proxy_body(dashboard, "/api/gateway/accounts")
        finally:
            await gateway_client.aclose()
            await upstream_client.aclose()

        assert result.returncode == 0
        assert runner.body == _SSE_BODY

        # Before the turn: configured, but nothing may claim it is active.
        anthropic_idle = _account(idle, "legacy-anthropic")
        assert anthropic_idle["configured"] is True
        assert anthropic_idle["in_flight"] is False
        assert anthropic_idle["health"] == "unverified"

        # While the turn streams: exactly one in-flight route, fully attributed.
        assert len(mid_stream["in_flight"]) == 1
        streaming = mid_stream["in_flight"][0]
        assert streaming["account_id"] == "legacy-anthropic"
        assert streaming["principal_id"] == "implementer"
        assert streaming["repo_slug"] == config.repo_slug
        assert len(mid_stream["leases"]) == 1

        # After the turn: the in-flight row is gone and the lease is revoked.
        assert settled_routes["in_flight"] == []
        assert settled_routes["leases"] == []
        assert _account(settled_accounts, "legacy-anthropic")["in_flight"] is False
        assert _account(settled_accounts, "legacy-anthropic")["observed"] is True
        assert _account(settled_accounts, "legacy-anthropic")["health"] == "healthy"

        # The operator's own surface sees the same terminal evidence.
        assert len(recent["data"]["routes"]) == 1
        terminal = recent["data"]["routes"][0]
        assert terminal["account_id"] == "legacy-anthropic"
        assert terminal["model_served"] == "claude-sonnet-4-6"
        assert terminal["status"] == "completed"
        assert terminal["worker_role"] == "implementer"

        # No credential reaches the operator surface at any point.
        assert _PROVIDER_KEY not in accounts_body
        assert _CONTROL_TOKEN not in accounts_body
        assert "scenario-virtual-secret" not in json.dumps(recent)


def _account(payload: dict[str, Any], account_id: str) -> dict[str, Any]:
    return next(a for a in payload["accounts"] if a["account_id"] == account_id)


async def _read(client: httpx.AsyncClient, path: str) -> dict[str, Any]:
    response = await client.get(
        path, headers={"authorization": f"Bearer {_CONTROL_TOKEN}"}
    )
    response.raise_for_status()
    return dict(response.json())


def _dashboard(config: Any, gateway_app: FastAPI) -> FastAPI:
    def reader_factory() -> GatewayControlReader:
        return GatewayControlReader(
            base_url=config.gateway_base_url,
            control_token=_CONTROL_TOKEN,
            client_factory=lambda: httpx.AsyncClient(
                transport=httpx.ASGITransport(app=gateway_app)
            ),
        )

    app = FastAPI()
    app.include_router(build_gateway_router(config, reader_factory=reader_factory))
    return app


async def _proxy_read(app: FastAPI, path: str) -> dict[str, Any]:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://dashboard.test"
    ) as client:
        response = await client.get(path)
        response.raise_for_status()
        return dict(response.json())


async def _proxy_body(app: FastAPI, path: str) -> str:
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://dashboard.test"
    ) as client:
        response = await client.get(path)
        response.raise_for_status()
        return response.text
