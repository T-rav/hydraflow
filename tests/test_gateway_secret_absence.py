"""No secret, credential, or credential fingerprint may reach a v2 read payload.

This is the machine-checked proof behind ADR-0138's zero-disclosure rule: the
account and route read models are asserted against realistic credential values,
the canonical ``secret_scrub`` pattern set, the model schemas themselves, and an
AST sweep proving the projection modules never unwrap a ``SecretStr``.
"""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from pydantic import SecretStr

import hydraflow_gateway.accounts as accounts_module
import hydraflow_gateway.active_routes as active_routes_module
import hydraflow_gateway.routing_audit as routing_audit_module
import hydraflow_gateway.routing_policy as routing_policy_module
import hydraflow_gateway.routing_store as routing_store_module
import route_shadow as route_shadow_module
from hydraflow_gateway.accounts import AccountView
from hydraflow_gateway.active_routes import (
    ActiveRouteRegistry,
    InFlightRouteView,
    LeaseView,
    TerminalRouteView,
)
from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayLedgerRow
from hydraflow_gateway.models import (
    GatewayRequestStatus,
    MintKeyRequest,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.routing_policy import (
    AccountAvailability,
    LegacyRoute,
    RouteContext,
    RouteDecision,
    RouteExplanation,
    RoutingPolicy,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from route_shadow import RouteStage, ShadowDecision
from secret_scrub import scan_for_secrets

# Every credential here is deliberately shaped like a real one, so the
# ``scan_for_secrets`` assertion is a live detector rather than a formality.
# Since #11635 that covers all four: ``secret_scrub`` carries ``hfgw_``
# virtual-key and ``hfgwctl_`` control-token patterns alongside the provider-key
# ones, so a leak of any of them now trips the canonical detector as well as its
# own explicit ``not in payload`` assertion below.
_CONTROL_TOKEN = "hfgwctl_" + "c" * 43
_ANTHROPIC_KEY = "sk-ant-" + "a" * 44
_ZAI_KEY = "sk-" + "z" * 48
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_AUTH = {"Authorization": f"Bearer {_CONTROL_TOKEN}"}
_READ_PATHS = (
    "/control/v2/accounts",
    "/control/v2/routes/active",
    "/control/v2/routes/recent",
)


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
                api_key=SecretStr(_ANTHROPIC_KEY),
                auth_style=UpstreamAuthStyle.X_API_KEY,
            ),
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://zai.test",
                api_key=SecretStr(_ZAI_KEY),
                auth_style=UpstreamAuthStyle.BEARER,
            ),
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
    )


def _row(request_id: str) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal={"kind": "spawn", "id": "implementer", "spawn_id": "spawn-1"},
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="full",
        timestamp=_NOW,
        latency_ms=12.0,
        status_code=200,
        status=GatewayRequestStatus.COMPLETED,
        upstream_provider=ProviderBinding.ANTHROPIC,
        path="/v1/messages",
        model_requested="glm-5.2",
        model_served="glm-5.3",
        body_capture_id="secret-body-handle",
        body_capture_complete=True,
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.0,
        cost_unknown=False,
    )


async def _payloads(tmp_path: Path) -> tuple[str, str]:
    """Return (minted virtual token, concatenated JSON of every v2 read payload)."""
    store = VirtualKeyStore(max_ttl_seconds=600)
    minted = store.mint(
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
    identity = store.resolve(minted.token)
    registry = ActiveRouteRegistry(started_at=_NOW)
    registry.register(
        request_id="req-live",
        identity=identity,
        path="/v1/messages",
        started_at=_NOW,
    )
    registry.register(
        request_id="req-done",
        identity=identity,
        path="/v1/messages",
        started_at=_NOW,
    )
    registry.release(_row("req-done"))

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    app = create_app(
        _settings(tmp_path),
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=registry,
        wall_clock=_NOW.timestamp,
    )
    bodies: list[str] = []
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        for path in _READ_PATHS:
            response = await client.get(path, headers=_AUTH)
            assert response.status_code == 200, path
            bodies.append(response.text)
    return minted.token, "\n".join(bodies)


async def test_read_payloads_carry_no_upstream_provider_key(tmp_path: Path) -> None:
    """A provider credential never crosses the account or route read plane."""
    _, payload = await _payloads(tmp_path)

    assert _ANTHROPIC_KEY not in payload


async def test_read_payloads_carry_no_second_upstream_provider_key(
    tmp_path: Path,
) -> None:
    """Every configured upstream is covered, not just the first one."""
    _, payload = await _payloads(tmp_path)

    assert _ZAI_KEY not in payload


async def test_read_payloads_carry_no_control_token(tmp_path: Path) -> None:
    """The credential that authenticates the read is never echoed by it."""
    _, payload = await _payloads(tmp_path)

    assert _CONTROL_TOKEN not in payload


async def test_read_payloads_carry_no_minted_virtual_token(tmp_path: Path) -> None:
    """A leased key's token stays with its worker; only its id is published."""
    token, payload = await _payloads(tmp_path)

    assert token not in payload


async def test_read_payloads_carry_no_virtual_token_secret_half(
    tmp_path: Path,
) -> None:
    """Publishing ``key_id`` must not publish the entropy that authenticates it."""
    token, payload = await _payloads(tmp_path)
    secret_half = token.split(".", maxsplit=1)[1]

    assert secret_half not in payload


async def test_read_payloads_carry_no_body_capture_handle(tmp_path: Path) -> None:
    """Captured prompt/response artifacts are not addressable from the read plane."""
    _, payload = await _payloads(tmp_path)

    assert "secret-body-handle" not in payload


async def test_read_payloads_trip_no_canonical_secret_pattern(
    tmp_path: Path,
) -> None:
    """The repo's canonical detector (ADR-0085) finds nothing to redact."""
    _, payload = await _payloads(tmp_path)

    assert scan_for_secrets(payload) == []


async def test_read_payloads_publish_the_lease_id_they_are_meant_to(
    tmp_path: Path,
) -> None:
    """The absence assertions are not vacuous: the sanitized join key IS present."""
    token, payload = await _payloads(tmp_path)
    key_id = token.removeprefix("hfgw_").split(".", maxsplit=1)[0]

    assert key_id in payload


@pytest.mark.parametrize(
    "marker",
    [
        pytest.param("req-live", id="the-in-flight-section-returned-a-row"),
        pytest.param("req-done", id="the-recent-section-returned-a-row"),
    ],
)
async def test_every_payload_section_actually_returned_a_row(
    tmp_path: Path, marker: str
) -> None:
    """Absence assertions over an empty section would prove nothing at all.

    ``body_capture_id`` only ever appears on a recent row, so the guard that
    protects it goes silently vacuous the moment that section empties out.
    """
    _, payload = await _payloads(tmp_path)

    assert marker in payload


@pytest.mark.parametrize(
    "model",
    [
        AccountView,
        LeaseView,
        InFlightRouteView,
        TerminalRouteView,
        # ADR-0139 adds a durable, hash-linked decision record. It is a
        # projection like the read models above, so it inherits the same
        # schema-level guard: a field named like a credential fails here
        # before it can ever be populated.
        AccountAvailability,
        LegacyRoute,
        RouteContext,
        RouteDecision,
        RouteExplanation,
        RoutingPolicy,
        RouteStage,
        ShadowDecision,
    ],
)
def test_read_model_declares_no_credential_shaped_field(model: type) -> None:
    """Schema-level guard: a future field named like a credential fails here."""
    forbidden = ("token", "secret", "api_key", "apikey", "digest", "fingerprint")
    named = [
        field
        for field in model.model_fields
        if any(marker in field.lower() for marker in forbidden)
    ]

    assert named == []


@pytest.mark.parametrize(
    "module",
    [
        accounts_module,
        active_routes_module,
        routing_policy_module,
        routing_store_module,
        routing_audit_module,
        route_shadow_module,
    ],
)
def test_projection_module_never_unwraps_a_secret(module: object) -> None:
    """AST guard: the sanitized projections never call ``get_secret_value``."""
    source = Path(module.__file__ or "").read_text(encoding="utf-8")
    calls = [
        node.func.attr
        for node in ast.walk(ast.parse(source))
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]

    assert "get_secret_value" not in calls


async def test_account_view_publishes_only_the_upstream_origin(
    tmp_path: Path,
) -> None:
    """The full upstream URL — path included — stays server-side."""
    _, payload = await _payloads(tmp_path)
    accounts = json.loads(payload.split("\n", maxsplit=1)[0])["accounts"]
    origins = [account["base_origin"] for account in accounts]

    assert origins == ["https://upstream.test", "https://zai.test"]
