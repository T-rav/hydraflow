"""One real governed gateway turn, for scenarios that need traffic to exist.

Extracted from ``test_gateway_route_shadow_scenario`` when the policy-workspace
scenario (#11538) needed the same live turn: the shadow scenario asks what a
turn *records*, the workspace scenario asks whether an operator's edit *moves*
one, and both need an identical, deterministic turn to ask it about.

Everything on the path is real — the gateway control plane, the harness
environment derivation, the mint, the streaming proxy, the active-route
registry, the ledger. Only the Claude subprocess and the external Anthropic
origin are fakes, and neither is an ``AsyncMock`` of a port: the origin is an
HTTP transport that records the bytes it was actually sent, which is what makes
"the upstream saw identical bytes" a claim about the wire rather than about a
mock's call list.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import SecretStr

from execution import SimpleResult
from gateway_coverage import gateway_ledger_path
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from runner_utils import (
    GatewayMintCredential,
    GatewayMintRequest,
    run_lightweight_agent,
)

if TYPE_CHECKING:
    from collections.abc import AsyncIterator, Sequence

SSE_BODY = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":11}}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)

TURN_MODEL = "claude-sonnet-4-6"


class FixedSseStream(httpx.AsyncByteStream):
    """Upstream body delivered as a stream, exactly as a real SSE origin would."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield SSE_BODY


@dataclass(slots=True)
class FakeAnthropicOrigin:
    """Deterministic external HTTP boundary that records what it was sent."""

    exchanges: list[tuple[str, bytes]] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        self.exchanges.append((str(request.url), body))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=FixedSseStream(),
        )


@dataclass(slots=True)
class InProcessGatewayControlClient:
    """Runner control adapter that drives the gateway's real mint endpoint."""

    client: httpx.AsyncClient

    async def mint_key(
        self, *, base_url: str, control_token: str, request: GatewayMintRequest
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


class GatewayHarnessRunner:
    """Claude stand-in that performs one streaming API turn using its derived env."""

    def __init__(self, client: httpx.AsyncClient) -> None:
        self._client = client

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
                "model": TURN_MODEL,
                "stream": True,
                "messages": [{"role": "user", "content": "scenario"}],
            },
        ) as response:
            response.raise_for_status()
            async for _chunk in response.aiter_bytes():
                pass
        return SimpleResult(stdout="gateway session complete", returncode=0)


@dataclass(frozen=True, slots=True)
class GatewayTurn:
    """What one real turn returned and what the external origin actually saw."""

    returncode: int
    exchanges: list[tuple[str, bytes]]


async def run_gateway_turn(
    *,
    config: Any,
    control_token: str,
    provider_key: str,
    virtual_secret: str,
    key_id: str = "gateway-scenario-key",
    source: str = "implementer",
) -> GatewayTurn:
    """Drive one real lightweight gateway spawn for *config* and report the wire."""
    ledger = GatewayLedger(gateway_ledger_path(config))
    settings = GatewaySettings(
        control_token=SecretStr(control_token),
        upstreams={
            ProviderBinding.ANTHROPIC: UpstreamSettings(
                base_url="https://anthropic.test",
                api_key=SecretStr(provider_key),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            )
        },
        ledger_path=ledger.path,
        body_dir=config.data_root / "gateway" / "bodies",
        max_key_ttl_seconds=config.gateway_key_ttl_seconds,
    )
    origin = FakeAnthropicOrigin()
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
    app = create_app(
        settings,
        key_store=VirtualKeyStore(
            max_ttl_seconds=config.gateway_key_ttl_seconds,
            id_factory=lambda: key_id,
            secret_factory=lambda: virtual_secret,
        ),
        client=upstream_client,
        ledger=ledger,
        body_store=GatewayBodyStore(settings.body_dir),
    )
    gateway_client = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url=config.gateway_base_url
    )
    try:
        result = await run_lightweight_agent(
            runner=GatewayHarnessRunner(gateway_client),  # type: ignore[arg-type]
            config=config,
            tool="claude",
            model=TURN_MODEL,
            prompt="Exercise one governed gateway turn.",
            source=source,
            timeout=10,
            provider="gateway",
            gateway_client=InProcessGatewayControlClient(gateway_client),
        )
    finally:
        await gateway_client.aclose()
        await upstream_client.aclose()
    return GatewayTurn(returncode=result.returncode, exchanges=origin.exchanges)
