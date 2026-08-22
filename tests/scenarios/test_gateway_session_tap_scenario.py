"""MockWorld scenario for the LLM gateway session tap.

The scenario keeps the real control plane, harness environment derivation,
streaming proxy, append-only ledger, and ``GatewayCoverageLoop`` wired.  Only
the Claude subprocess and external Anthropic HTTP origin are deterministic
stateful fakes.
"""

from __future__ import annotations

import json
from collections.abc import AsyncIterator, Sequence
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

import httpx
import pytest
from pydantic import SecretStr

from execution import SimpleResult
from gateway_coverage import (
    gateway_coverage_snapshot_path,
    gateway_ledger_path,
)
from gateway_mint_client import GatewayMintCredential, GatewayMintRequest
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import InvalidVirtualKey, VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from runner_utils import _claude_cli_complete
from tests.helpers import ConfigFactory
from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario_loops

_CONTROL_TOKEN = "scenario-control-token-0123456789abcdef"
_PROVIDER_KEY = "scenario-real-provider-key"
_SSE_BODY = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":11}}}\n\n'
    b'event: content_block_start\ndata: {"type":"content_block_start",'
    b'"index":0,"content_block":{"type":"tool_use","id":"tool-1",'
    b'"name":"Read","input":{}}}\n\n'
    b'event: message_delta\ndata: {"type":"message_delta","usage":'
    b'{"output_tokens":17}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _ChunkStream(httpx.AsyncByteStream):
    """Deterministic streaming body for the external-provider fake."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        midpoint = len(_SSE_BODY) // 2
        yield _SSE_BODY[:midpoint]
        yield _SSE_BODY[midpoint:]


@dataclass(frozen=True, slots=True)
class _UpstreamExchange:
    method: str
    url: str
    headers: httpx.Headers
    body: bytes


@dataclass(slots=True)
class _FakeAnthropicOrigin:
    """Stateful external HTTP boundary observed through completed exchanges."""

    exchanges: list[_UpstreamExchange] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        self.exchanges.append(
            _UpstreamExchange(
                method=request.method,
                url=str(request.url),
                headers=httpx.Headers(request.headers),
                body=await request.aread(),
            )
        )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_ChunkStream(),
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
        self,
        *,
        base_url: str,
        control_token: str,
        key_id: str,
    ) -> bool:
        response = await self.client.delete(
            f"{base_url.rstrip('/')}/control/v1/keys/{key_id}",
            headers={"authorization": f"Bearer {control_token}"},
        )
        response.raise_for_status()
        return bool(response.json()["revoked"])


@dataclass(slots=True)
class _HarnessWorkerState:
    """Observable state left by the deterministic Claude subprocess boundary."""

    environments: list[dict[str, str]] = field(default_factory=list)
    response_bodies: list[bytes] = field(default_factory=list)


class _GatewayHarnessRunner:
    """Claude stand-in that performs one API turn using its derived env."""

    def __init__(self, client: httpx.AsyncClient, state: _HarnessWorkerState) -> None:
        self._client = client
        self._state = state

    async def run_simple(
        self,
        _cmd: Sequence[str],
        *,
        env: dict[str, str] | None = None,
        **_kwargs: Any,
    ) -> SimpleResult:
        worker_env = dict(env or {})
        response = await self._client.post(
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
        )
        response.raise_for_status()
        self._state.environments.append(worker_env)
        self._state.response_bodies.append(response.content)
        return SimpleResult(stdout="gateway session complete", returncode=0)


class TestGatewaySessionTapScenario:
    """Mint -> isolated worker -> transit -> ledger -> coverage gauge."""

    async def test_gateway_transit_produces_complete_spend_coverage(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
        monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
        monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)
        monkeypatch.setenv("ANTHROPIC_API_KEY", "ambient-real-anthropic-key")
        monkeypatch.setenv("ANTHROPIC_AUTH_TOKEN", "ambient-real-auth-token")
        monkeypatch.setenv("OPENAI_ADMIN_KEY", "ambient-real-admin-key")

        config = ConfigFactory.create(repo_root=tmp_path / "repo")
        world = MockWorld(tmp_path, config=config)
        ledger = GatewayLedger(gateway_ledger_path(config))
        key_store = VirtualKeyStore(
            max_ttl_seconds=config.gateway_key_ttl_seconds,
            id_factory=lambda: "scenario-key",
            secret_factory=lambda: "scenario-virtual-secret",
        )
        upstream = _FakeAnthropicOrigin()
        upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(upstream))
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
        worker_state = _HarnessWorkerState()

        try:
            result = await _claude_cli_complete(
                runner=_GatewayHarnessRunner(gateway_client, worker_state),  # type: ignore[arg-type]
                tool="claude",
                model="claude-sonnet-4-6",
                prompt="Exercise one tool-using gateway turn.",
                timeout=10,
                gh_token="scenario-gh-token",
                isolate_user_settings=True,
                provider="gateway",
                config=config,
                source="adr_reviewer",
                session_id="scenario-session",
                gateway_client=_InProcessGatewayControlClient(gateway_client),
            )
        finally:
            await gateway_client.aclose()
            await upstream_client.aclose()

        assert result.returncode == 0
        assert key_store.active_count == 0
        assert len(worker_state.environments) == 1
        worker_env = worker_state.environments[0]
        virtual_token = worker_env["ANTHROPIC_AUTH_TOKEN"]
        assert worker_env["ANTHROPIC_BASE_URL"] == config.gateway_base_url
        assert worker_env["ANTHROPIC_API_KEY"] == ""
        assert virtual_token.startswith("hfgw_scenario-key.")
        assert _PROVIDER_KEY not in worker_env.values()
        assert "HYDRAFLOW_GATEWAY_CONTROL_TOKEN" not in worker_env
        assert "OPENAI_ADMIN_KEY" not in worker_env
        with pytest.raises(InvalidVirtualKey, match="unknown virtual key"):
            key_store.resolve(virtual_token)

        assert worker_state.response_bodies == [_SSE_BODY]
        assert len(upstream.exchanges) == 1
        exchange = upstream.exchanges[0]
        assert exchange.method == "POST"
        assert exchange.url == "https://anthropic.test/v1/messages"
        assert exchange.headers["x-api-key"] == _PROVIDER_KEY
        assert virtual_token not in exchange.headers.values()
        assert json.loads(exchange.body)["model"] == "claude-sonnet-4-6"

        rows = ledger.read_all()
        assert len(rows) == 1
        row = rows[0]
        assert row.key_id == "scenario-key"
        assert row.repo_slug == config.repo_slug
        assert row.model_served == "claude-sonnet-4-6"
        assert row.input_tokens == 11
        assert row.output_tokens == 17
        assert row.completed is True
        assert row.cost_unknown is False
        assert row.cost_usd is not None and row.cost_usd > 0
        expected_gateway_spend = round(row.cost_usd, 6)

        # The coverage contract requires both append-only sources to be
        # available before it can make a complete claim. This private harness
        # seam intentionally emits no duplicate PromptTelemetry row, so expose
        # an explicitly empty, readable denominator instead of treating a
        # missing file as proof that no bypass occurred.
        config.cost_inferences_path.parent.mkdir(parents=True, exist_ok=True)
        config.cost_inferences_path.write_text("")

        stats = await world.run_with_loops(["gateway_coverage"], cycles=1)

        coverage = stats["gateway_coverage"]
        assert coverage is not None
        assert coverage["coverage_status"] == "complete"
        assert coverage["coverage_percent"] == 100.0
        assert coverage["gateway_requests"] == 1
        assert coverage["bypass_requests"] == 0

        snapshot = json.loads(gateway_coverage_snapshot_path(config).read_text())
        assert snapshot["gateway_spend_usd"] == expected_gateway_spend
        assert snapshot["known_total_spend_usd"] == expected_gateway_spend
        assert snapshot["bypass_spend_usd"] == 0.0
