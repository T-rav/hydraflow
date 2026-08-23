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

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Any

import httpx
from pydantic import SecretStr

from execution import SimpleResult
from gateway_coverage import gateway_ledger_path
from gateway_mint_client import (
    GatewayMintCredential,
    GatewayMintRequest,
    GatewayMintV2Request,
)
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from prompt_telemetry import parse_command_tool_model
from runner_utils import run_lightweight_agent

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


class GovernedMintRefused(RuntimeError):
    """The gateway answered a v2 attempt with a held or rejected decision."""


@dataclass(slots=True)
class InProcessGatewayControlClient:
    """Runner control adapter that drives the gateway's real mint endpoints.

    Routes by request type exactly as the production adapter does, so a scenario
    exercising ADR-0141's canary reaches ``/control/v2/keys`` and a scenario
    exercising the ungoverned path still reaches ``/control/v1/keys``. The last
    decision is retained because the scenario needs to read the lineage the
    gateway stamped, not a lineage the test invented.
    """

    client: httpx.AsyncClient
    decisions: list[dict[str, Any]] = field(default_factory=list)

    async def mint_key(
        self,
        *,
        base_url: str,
        control_token: str,
        request: GatewayMintRequest | GatewayMintV2Request,
    ) -> GatewayMintCredential:
        governed = isinstance(request, GatewayMintV2Request)
        route = "/control/v2/keys" if governed else "/control/v1/keys"
        response = await self.client.post(
            f"{base_url.rstrip('/')}{route}",
            headers={"authorization": f"Bearer {control_token}"},
            # ``wire_payload()``, not ``asdict()``: the production body omits
            # unset attribution rather than sending nulls, and the control
            # models forbid extras — a scenario posting the dataclass verbatim
            # would never exercise the shape a real spawn sends.
            json=request.wire_payload(),
        )
        response.raise_for_status()
        payload = response.json()
        if governed:
            decision = dict(payload["decision"])
            self.decisions.append(decision)
            if decision["outcome"] != "selected":
                raise GovernedMintRefused(f"{decision['outcome']}/{decision['reason']}")
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
        # A real CLI sends the model it was invoked with. Reading it off the argv
        # rather than hardcoding it is what lets a scenario observe a routing
        # decision reaching the wire at all.
        _, argv_model = parse_command_tool_model(list(_cmd))
        async with self._client.stream(
            "POST",
            "/v1/messages",
            headers={
                "authorization": f"Bearer {worker_env['ANTHROPIC_AUTH_TOKEN']}",
                "anthropic-version": "2023-06-01",
            },
            json={
                "model": argv_model or TURN_MODEL,
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
    decisions: list[dict[str, Any]] = field(default_factory=list)


async def run_gateway_turn(
    *,
    config: Any,
    control_token: str,
    provider_key: str,
    virtual_secret: str,
    key_id: str = "gateway-scenario-key",
    source: str = "implementer",
    zai_upstream: bool = False,
    governed_repo_slugs: frozenset[str] = frozenset(),
) -> GatewayTurn:
    """Drive one real lightweight gateway spawn for *config* and report the wire."""
    ledger = GatewayLedger(gateway_ledger_path(config))
    upstreams = {
        ProviderBinding.ANTHROPIC: UpstreamSettings(
            base_url="https://anthropic.test",
            api_key=SecretStr(provider_key),
            auth_style=UpstreamAuthStyle.X_API_KEY,
        )
    }
    if zai_upstream:
        upstreams[ProviderBinding.ZAI_HARNESS] = UpstreamSettings(
            base_url="https://zai.test",
            api_key=SecretStr(f"{provider_key}-zai"),
            auth_style=UpstreamAuthStyle.BEARER,
        )
    settings = GatewaySettings(
        control_token=SecretStr(control_token),
        upstreams=upstreams,
        governed_repo_slugs=governed_repo_slugs,
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
    control = InProcessGatewayControlClient(gateway_client)
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
            gateway_client=control,
        )
    finally:
        await gateway_client.aclose()
        await upstream_client.aclose()
    return GatewayTurn(
        returncode=result.returncode,
        exchanges=origin.exchanges,
        decisions=control.decisions,
    )
