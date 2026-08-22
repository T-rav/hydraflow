"""MockWorld scenario: a shadow routing decision recorded beside a real turn.

Everything on the path is real — the lightweight spawn seam, the gateway control
plane, the harness environment derivation, the mint, the streaming proxy, the
active-route registry, the durable policy store, and the hash-linked decision
chain. Only the Claude subprocess and the external Anthropic origin are
deterministic fakes; no port is an ``AsyncMock``.

The scenario proves the phase's safety property end to end rather than in a unit:
a policy that *would* send this repo to z.ai is written, loaded, matched, and
recorded as a divergence — while the live turn still reaches Anthropic through
the gateway with the same bytes it would have sent with the resolver switched
off entirely.
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
from gateway_coverage import gateway_ledger_path
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding
from hydraflow_gateway.routing_audit import RoutingAuditLog
from hydraflow_gateway.routing_policy import (
    RequirementMapping,
    RouteTransport,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from route_shadow import (
    ShadowDivergence,
    policy_snapshot_path,
    requirement_for_model,
    shadow_decision_log_path,
)
from runner_utils import (
    GatewayMintCredential,
    GatewayMintRequest,
    run_lightweight_agent,
)
from tests.helpers import ConfigFactory

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "shadow-scenario-control-token-0123456789"
_PROVIDER_KEY = "shadow-scenario-real-provider-key"
_VIRTUAL_SECRET = "shadow-scenario-virtual-secret"
_REPO = "acme/project-x"
_SSE_BODY = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"claude-sonnet-4-6","usage":{"input_tokens":11}}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _FixedStream(httpx.AsyncByteStream):
    """Upstream body delivered as a stream, exactly as a real SSE origin would."""

    async def __aiter__(self) -> AsyncIterator[bytes]:
        yield _SSE_BODY


@dataclass(slots=True)
class _FakeAnthropicOrigin:
    """Deterministic external HTTP boundary that records what it was sent."""

    exchanges: list[tuple[str, bytes]] = field(default_factory=list)

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        body = await request.aread()
        self.exchanges.append((str(request.url), body))
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_FixedStream(),
        )


@dataclass(slots=True)
class _InProcessGatewayControlClient:
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


class _GatewayHarnessRunner:
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
                "model": "claude-sonnet-4-6",
                "stream": True,
                "messages": [{"role": "user", "content": "scenario"}],
            },
        ) as response:
            response.raise_for_status()
            async for _chunk in response.aiter_bytes():
                pass
        return SimpleResult(stdout="gateway session complete", returncode=0)


@dataclass(slots=True)
class _World:
    """What one full turn left behind for the assertions to read."""

    config: Any
    returncode: int
    exchanges: list[tuple[str, bytes]]
    decisions: list[dict[str, Any]]
    chain_ok: bool
    chain_text: str


async def _run_turn(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    *,
    shadow: bool,
    policies: Sequence[RoutingPolicy] = (),
) -> _World:
    """Drive one real lightweight gateway spawn and return everything it left."""
    monkeypatch.delenv("HYDRAFLOW_DATA_ROOT", raising=False)
    monkeypatch.delenv("HYDRAFLOW_HOME", raising=False)
    monkeypatch.setenv("HYDRAFLOW_GATEWAY_CONTROL_TOKEN", _CONTROL_TOKEN)

    config = ConfigFactory.create(repo_root=tmp_path / "repo", repo=_REPO)
    config.gateway_route_shadow_enabled = shadow
    if policies:
        RoutingPolicyStore(policy_snapshot_path(config)).save(policies)

    ledger = GatewayLedger(gateway_ledger_path(config))
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
    origin = _FakeAnthropicOrigin()
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
    app = create_app(
        settings,
        key_store=VirtualKeyStore(
            max_ttl_seconds=config.gateway_key_ttl_seconds,
            id_factory=lambda: "shadow-scenario-key",
            secret_factory=lambda: _VIRTUAL_SECRET,
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
            runner=_GatewayHarnessRunner(gateway_client),  # type: ignore[arg-type]
            config=config,
            tool="claude",
            model="claude-sonnet-4-6",
            prompt="Exercise one governed gateway turn.",
            source="implementer",
            timeout=10,
            provider="gateway",
            gateway_client=_InProcessGatewayControlClient(gateway_client),
        )
    finally:
        await gateway_client.aclose()
        await upstream_client.aclose()

    log = RoutingAuditLog(shadow_decision_log_path(config))
    path = shadow_decision_log_path(config)
    return _World(
        config=config,
        returncode=result.returncode,
        exchanges=origin.exchanges,
        decisions=[record.payload for record in log.read_all()]
        if path.exists()
        else [],
        chain_ok=log.verify().ok if path.exists() else False,
        chain_text=path.read_text(encoding="utf-8") if path.exists() else "",
    )


def _zai_lock() -> RoutingPolicy:
    """The design's "project X always uses z.ai", written the honest way.

    The lock alone is not enough and must not be: this turn asks for
    ``claude-sonnet-4-6``, and moving an Anthropic request onto a z.ai lane
    requires an operator to say so in a mapping (ADR-0139 D4). ``_bare_zai_lock``
    below is the same policy without that mapping, and it holds instead.
    """
    return RoutingPolicy(
        id="project-x-zai",
        priority=100,
        match=RoutingMatch(repo_ids=(_REPO,)),
        action=RoutingAction(
            provider_lock=ProviderBinding.ZAI_HARNESS,
            requirement_map=(
                RequirementMapping(
                    requirement=requirement_for_model("claude-sonnet-4-6"),
                    effective_model="glm-5.3",
                ),
            ),
        ),
    )


def _bare_zai_lock() -> RoutingPolicy:
    """A provider lock with no mapping — it may not silently remap the model."""
    return RoutingPolicy(
        id="project-x-zai-bare",
        priority=100,
        match=RoutingMatch(repo_ids=(_REPO,)),
        action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
    )


class TestGatewayRouteShadowScenario:
    """One real governed turn, shadowed — and unmoved by the policy shadowing it."""

    async def test_the_turn_succeeds_with_the_resolver_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The control case: shadow recording does not break a real spawn."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)

        assert world.returncode == 0

    async def test_the_upstream_sees_identical_bytes_with_the_resolver_enabled(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The shadow-safety property, proven at the external boundary."""
        dark = await _run_turn(tmp_path / "dark", monkeypatch, shadow=False)
        lit = await _run_turn(tmp_path / "lit", monkeypatch, shadow=True)

        assert lit.exchanges == dark.exchanges

    async def test_a_governed_spawn_records_exactly_one_shadow_decision(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """One decision per resolve attempt — not zero, not two."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)

        assert len(world.decisions) == 1

    async def test_the_shadow_decision_joins_the_gateway_s_own_account_id(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """ADR-0138's join key is the one the resolver records, not a new id."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)

        assert world.decisions[0]["actual"]["account_id"] == "legacy-anthropic"

    async def test_a_gateway_routed_spawn_is_recorded_as_governed_transport(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Traffic through the tap is the only traffic a policy could ever bind."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)

        assert world.decisions[0]["actual"]["transport"] == RouteTransport.GATEWAY.value

    async def test_the_recorded_chain_verifies_after_a_real_turn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A chain written by the live path must be as verifiable as a unit's."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)

        assert world.chain_ok

    async def test_no_credential_reaches_the_recorded_chain(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The chain is durable, so a leaked key in it would be permanent."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)
        stored = world.chain_text

        assert _PROVIDER_KEY not in stored
        assert _CONTROL_TOKEN not in stored
        assert _VIRTUAL_SECRET not in stored

    async def test_a_policy_locking_this_repo_to_zai_does_not_move_the_live_turn(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Enforcement is off: the turn still reaches Anthropic through the tap."""
        dark = await _run_turn(tmp_path / "dark", monkeypatch, shadow=False)
        lit = await _run_turn(
            tmp_path / "lit", monkeypatch, shadow=True, policies=[_zai_lock()]
        )

        assert lit.exchanges == dark.exchanges

    async def test_that_policy_is_recorded_as_a_route_divergence(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The measurement P2 burns in on: what enforcement *would* have changed."""
        monkeypatch.setenv("ZAI_API_KEY", "scenario-zai-key")
        world = await _run_turn(
            tmp_path, monkeypatch, shadow=True, policies=[_zai_lock()]
        )

        assert (
            world.decisions[0]["divergence"]
            == ShadowDivergence.PROVIDER_AND_MODEL.value
        )

    async def test_a_bare_provider_lock_holds_rather_than_remapping_the_model(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A lock cannot move an Anthropic request to z.ai on its own authority."""
        monkeypatch.setenv("ZAI_API_KEY", "scenario-zai-key")
        world = await _run_turn(
            tmp_path, monkeypatch, shadow=True, policies=[_bare_zai_lock()]
        )

        assert world.decisions[0]["proposed"]["outcome"] == "held"

    async def test_the_divergent_decision_cites_the_policy_that_proposed_it(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A recorded divergence nobody can trace to a rule is not evidence."""
        monkeypatch.setenv("ZAI_API_KEY", "scenario-zai-key")
        world = await _run_turn(
            tmp_path, monkeypatch, shadow=True, policies=[_zai_lock()]
        )

        assert world.decisions[0]["proposed"]["policy_id"] == "project-x-zai"

    async def test_the_decision_records_the_snapshot_revision_it_resolved_against(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Without the revision the decision cannot be replayed after an edit."""
        world = await _run_turn(
            tmp_path, monkeypatch, shadow=True, policies=[_zai_lock()]
        )

        assert world.decisions[0]["proposed"]["policy_revision"] == 1

    async def test_the_switch_off_writes_no_decision_chain_at_all(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """The kill switch stops the write, not merely the content of it."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=False)

        assert not shadow_decision_log_path(world.config).exists()

    async def test_the_recorded_context_is_complete_enough_to_replay(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An explanation that cannot be rebuilt from its record is not one."""
        world = await _run_turn(tmp_path, monkeypatch, shadow=True)
        context = world.decisions[0]["proposed"]["explanation"]["context"]

        assert json.dumps(context, sort_keys=True)
        assert context["repo"]["canonical"] == _REPO
        assert context["legacy_route"]["provider_binding"] == "anthropic"
