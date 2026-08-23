"""No secret, credential, or credential fingerprint may reach a routing payload.

This is the machine-checked proof behind ADR-0138's zero-disclosure rule: the
account and route read models are asserted against realistic credential values,
the canonical ``secret_scrub`` pattern set, the model schemas themselves, and an
AST sweep proving the projection modules never unwrap a ``SecretStr``.

ADR-0140 extends the same file rather than adding a second scanner, and adds the
one thing a write plane has that a read plane does not: a payload an **operator**
supplies. A policy is durable, is written without redaction (``atomic_write``,
unlike the audit chain's ``append_jsonl``), and is served back over an
unauthenticated read route — so a credential pasted into a policy body is refused
at write time, and the refusal does not quote it back.

ADR-0141 extends it again for the route-aware mint. ``POST /control/v2/keys`` is
the one route that both *receives* a caller-supplied identity and *returns* live
credential material, so it is the nearest thing in the system to a disclosure —
and its decision half, which is echoed onto a lease view, an in-flight view, a
terminal view and a durable ledger row, must carry none of it.

ADR-0142 (#11540) extends it once more for multi-account pools. A pool moves the
credential question from "the two compiled env pairs" to "a **file** a deployment
writes", and adds a second write plane — the audited administrative overlay an
operator drains an account with. Both halves land on the existing sweeps: the
registry models prove a file-backed account can never grow a field to paste a key
into, and the admin routes prove the mutation an operator makes under the control
token never echoes it back.
"""

from __future__ import annotations

import ast
import json
from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

import dashboard_routes._gateway_policy_routes as gateway_policy_routes_module
import hydraflow_gateway.accounts as accounts_module
import hydraflow_gateway.active_routes as active_routes_module
import hydraflow_gateway.governed_preflight as governed_preflight_module
import hydraflow_gateway.route_mint as route_mint_module
import hydraflow_gateway.routing_account_admin as routing_account_admin_module
import hydraflow_gateway.routing_account_state as routing_account_state_module
import hydraflow_gateway.routing_accounts as routing_accounts_module
import hydraflow_gateway.routing_audit as routing_audit_module
import hydraflow_gateway.routing_fallback as routing_fallback_module
import hydraflow_gateway.routing_policy as routing_policy_module
import hydraflow_gateway.routing_store as routing_store_module
import hydraflow_gateway.routing_workspace as routing_workspace_module
import operator_identity as operator_identity_module
import route_shadow as route_shadow_module
import routing_matrix as routing_matrix_module
from dashboard_routes._gateway_policy_routes import build_gateway_policy_router
from hydraflow_gateway.accounts import AccountLiveFacts, AccountView
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
    GatewayIdentity,
    GatewayRequestStatus,
    MintKeyRequest,
    ProviderBinding,
    RepoClass,
    RouteBinding,
)
from hydraflow_gateway.route_mint import MintDecisionView, MintV2Request
from hydraflow_gateway.routing_account_admin import (
    AccountAdminAuditView,
    AccountAdminEntry,
    AccountStateRequest,
    AccountStateResponse,
    RevokeLeasesRequest,
    RevokeLeasesResponse,
)
from hydraflow_gateway.routing_accounts import AccountRegistry, GatewayAccount
from hydraflow_gateway.routing_policy import (
    AccountAvailability,
    LegacyRoute,
    RouteContext,
    RouteDecision,
    RouteExplanation,
    RoutingPolicy,
)
from hydraflow_gateway.routing_workspace import MutationIntent, PolicyMutation
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
from route_shadow import RouteStage, ShadowDecision
from secret_scrub import scan_for_secrets
from tests.helpers import ConfigFactory

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
        # ADR-0142's admin overlay is a hash-linked chain on disk. Pointed at
        # ``tmp_path`` rather than the packaged default so a sweep reads the
        # chain this test wrote, not one a previous run left in the repo.
        account_state_dir=tmp_path / "accounts",
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
        # ADR-0140's write plane. A mutation body and its write-ahead journal
        # both cross a durable boundary, so they inherit the same schema guard
        # rather than growing one of their own.
        PolicyMutation,
        MutationIntent,
        # ADR-0141's route-aware mint. ``MintV2Response`` is deliberately absent:
        # it is the one-time credential envelope, exactly like ``MintKeyResponse``,
        # and its ``token`` field is the payload rather than a leak. Its
        # *decision* half is not, and neither is the binding stamped onto every
        # governed identity, ledger row, and route view — so both are guarded.
        MintV2Request,
        MintDecisionView,
        RouteBinding,
        # ADR-0142 (#11540) multi-account pools. ``GatewayAccount`` is the one
        # model here that is populated from a **file a deployment writes**, so
        # this guard is what keeps a future ``api_key`` field from existing for
        # someone to paste a key into: the account names the *variable* that
        # configures it (``credential_env``) and never a value. The registry that
        # holds them is swept for the same reason a container is swept.
        GatewayAccount,
        AccountRegistry,
        # The live pool facts fed into the account read model. It rides beside
        # ``AccountView`` on the wire, so it inherits ``AccountView``'s guard.
        AccountLiveFacts,
        # ADR-0142's administrative overlay: two operator-supplied request bodies
        # and the three read models the mutations answer with. The write half is
        # swept for ADR-0140's reason — a body an operator composes is where a
        # pasted credential enters — and the read half because both responses and
        # the audit projection are echoes of a durable, hash-linked chain.
        AccountStateRequest,
        AccountStateResponse,
        RevokeLeasesRequest,
        RevokeLeasesResponse,
        AccountAdminEntry,
        AccountAdminAuditView,
        # Flagged by a PR-#11653 review as missing from this sweep rather than
        # failing it: ``GatewayIdentity`` is the non-secret half every valid
        # virtual key resolves to, is stamped onto every ledger row and route
        # view, and had simply never been listed.
        GatewayIdentity,
        # ``GatewayLedgerRow`` was flagged by the same review and is deliberately
        # NOT here: it declares ADR-0138's four usage counters — ``input_tokens``,
        # ``output_tokens``, ``cache_read_input_tokens``,
        # ``cache_creation_input_tokens`` — which are billing counts, not
        # credential material, and the substring marker ``token`` cannot tell the
        # two apart. Listing it would mean loosening the marker set for all 24
        # models above to admit one, which trades a real guard for a nominal
        # entry. The row is already covered where it matters: ``_row()`` drives a
        # populated row through ``/control/v2/routes/recent`` in ``_payloads``,
        # so its wire projection is swept by every absence assertion in this file.
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
        routing_workspace_module,
        routing_matrix_module,
        gateway_policy_routes_module,
        governed_preflight_module,
        route_mint_module,
        # ADR-0142 (#11540). ``routing_accounts`` is on the sweep despite being
        # the module that *builds* credentials: it wraps a raw environment value
        # into ``UpstreamSettings(api_key=SecretStr(...))`` and hands the result
        # to ``AccountPool``, which is a plain object precisely so nothing here
        # has to unwrap one again. The other three are pure projection and
        # decision code over the pool.
        routing_accounts_module,
        routing_account_state_module,
        routing_account_admin_module,
        routing_fallback_module,
        # The one module that legitimately handles a credential: it must still
        # never unwrap a ``SecretStr`` into anything it returns or records.
        operator_identity_module,
        # ``hydraflow_gateway.settings`` stays off this sweep, as it has since
        # ADR-0138: it is the module that *validates* a credential's header
        # shape, so unwrapping is its job rather than a leak. ``app`` is off for
        # the same reason — it unwraps the control token once, to compare against
        # an inbound header. Everything downstream of those two is swept.
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


# --------------------------------------------------------------------------
# ADR-0140's policy workspace: the same rule on the first WRITE surface
# --------------------------------------------------------------------------

_OPERATOR_TOKEN = "hfop_" + "o" * 40
_POLICY_REPO = "acme/hydraflow"


def _policy_body(
    policy_id: str = "pin-zai", model: str = "glm-5.3"
) -> dict[str, object]:
    return {
        "id": policy_id,
        "match": {"repo_ids": [_POLICY_REPO]},
        "action": {
            "provider_lock": "zai-harness",
            "requirement_map": [
                {
                    "requirement": {"kind": "capability", "value": "balanced"},
                    "effective_model": model,
                }
            ],
        },
    }


def _policy_client(tmp_path: Path) -> TestClient:
    config = ConfigFactory.create(repo=_POLICY_REPO, dashboard_host="127.0.0.1")
    object.__setattr__(config, "data_root", tmp_path / "policy-data")
    object.__setattr__(config, "gateway_policy_workspace_enabled", True)
    app = FastAPI()
    app.include_router(
        build_gateway_policy_router(
            config,
            env={OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN, OPERATOR_ID_ENV: "operator"},
            clock=lambda: _NOW,
        )
    )
    return TestClient(app)


def _policy_plane_payloads(tmp_path: Path) -> str:
    """Every policy-plane response, including the authenticated write's own."""
    client = _policy_client(tmp_path)
    auth = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}
    bodies = [
        client.post(
            "/api/gateway/policies/mutations",
            json={
                "kind": "create",
                "expected_revision": 0,
                "policy": _policy_body(),
            },
            headers=auth,
        ).text,
        client.post(
            "/api/gateway/policies/preview",
            json={
                "kind": "create",
                "expected_revision": 1,
                "policy": _policy_body("second"),
            },
        ).text,
    ]
    bodies.extend(
        client.get(f"/api/gateway/policies{suffix}").text
        for suffix in ("", "/effective", "/audit")
    )
    return "\n".join(bodies)


def test_policy_plane_payloads_carry_no_operator_token(tmp_path: Path) -> None:
    """The credential that authorises a policy write is never echoed by one."""
    payload = _policy_plane_payloads(tmp_path)

    assert _OPERATOR_TOKEN not in payload


def test_policy_plane_payloads_trip_no_canonical_secret_pattern(
    tmp_path: Path,
) -> None:
    """The repo's canonical detector (ADR-0085) finds nothing to redact."""
    payload = _policy_plane_payloads(tmp_path)

    assert scan_for_secrets(payload) == []


def test_policy_plane_payloads_publish_the_policy_they_are_meant_to(
    tmp_path: Path,
) -> None:
    """The absence assertions are not vacuous: the policy IS on the wire."""
    payload = _policy_plane_payloads(tmp_path)

    assert payload.count("pin-zai") > 1


def test_a_credential_shaped_policy_value_is_refused_before_it_is_stored(
    tmp_path: Path,
) -> None:
    """The snapshot is not scrubbed on write and is served unauthenticated."""
    response = _policy_client(tmp_path).post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(model=_ANTHROPIC_KEY),
        },
        headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"},
    )

    assert (response.status_code, response.json()["code"]) == (
        422,
        "credential-shaped-value",
    )


def test_the_refusal_does_not_quote_the_credential_back(tmp_path: Path) -> None:
    """An error message that echoed the pasted key would itself be the leak."""
    response = _policy_client(tmp_path).post(
        "/api/gateway/policies/mutations",
        json={
            "kind": "create",
            "expected_revision": 0,
            "policy": _policy_body(model=_ANTHROPIC_KEY),
        },
        headers={"Authorization": f"Bearer {_OPERATOR_TOKEN}"},
    )

    assert _ANTHROPIC_KEY not in response.text


# --------------------------------------------------------------------------
# ADR-0141's route-aware mint: the one route that returns live key material
# --------------------------------------------------------------------------

_V2_BODY = {
    "mint_attempt_id": "att-1",
    "dispatch_id": "disp-1",
    "principal_kind": "spawn",
    "principal_id": "implementer",
    "spawn_id": "spawn-1",
    "repo": "acme/hydraflow",
    "repo_slug": "acme-hydraflow",
    "repo_class": "hydraflow",
    "worker_role": "implementer",
    "request_face": "agentic",
    "requirement_kind": "capability",
    "requirement_value": "balanced",
    "requested_model": "claude-sonnet-4-6",
    "effective_model": "glm-5.3",
    "route_decision_id": "dec_abc",
    "policy_id": "project-x-zai",
    "policy_revision": 4,
    "snapshot_hash": "sha256:feed",
    "capture_bodies": False,
    "ttl_seconds": 300,
}


async def _governed_mint(tmp_path: Path) -> tuple[str, str]:
    """Drive one real v2 mint and return (issued token, the decision payload)."""
    app = create_app(_settings(tmp_path), wall_clock=_NOW.timestamp)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        response = await client.post("/control/v2/keys", headers=_AUTH, json=_V2_BODY)
    assert response.status_code == 200, response.text
    payload = response.json()
    assert payload["decision"]["outcome"] == "selected", payload
    return str(payload["token"]), json.dumps(payload["decision"])


@pytest.mark.parametrize(
    "credential",
    [
        pytest.param(_ANTHROPIC_KEY, id="the-anthropic-upstream-key"),
        pytest.param(_ZAI_KEY, id="the-zai-upstream-key"),
        pytest.param(_CONTROL_TOKEN, id="the-control-token-that-authorised-the-mint"),
    ],
)
async def test_the_mint_decision_carries_no_credential(
    tmp_path: Path, credential: str
) -> None:
    """All four shapes are covered: the fourth is the minted token, below."""
    _, decision = await _governed_mint(tmp_path)

    assert credential not in decision


async def test_the_mint_decision_carries_no_part_of_the_key_it_authorised(
    tmp_path: Path,
) -> None:
    """The decision is echoed onto a ledger row and three route views."""
    token, decision = await _governed_mint(tmp_path)

    assert token not in decision


async def test_the_mint_decision_carries_no_virtual_token_secret_half(
    tmp_path: Path,
) -> None:
    """``key_id`` is a published join column; the entropy behind it is not."""
    token, decision = await _governed_mint(tmp_path)
    secret_half = token.split(".", maxsplit=1)[1]

    assert secret_half not in decision


async def test_the_mint_decision_trips_no_canonical_secret_pattern(
    tmp_path: Path,
) -> None:
    """The canonical detector (ADR-0085) finds nothing to redact."""
    _, decision = await _governed_mint(tmp_path)

    assert scan_for_secrets(decision) == []


async def test_the_mint_decision_publishes_the_join_keys_it_is_meant_to(
    tmp_path: Path,
) -> None:
    """The absence assertions above are not vacuous: the correlation IS present."""
    _, decision = await _governed_mint(tmp_path)

    assert "dec_abc" in decision


# --------------------------------------------------------------------------
# ADR-0142's account admin plane: the write surface an operator drains with
# --------------------------------------------------------------------------

_ADMIN_ACCOUNT = "legacy-zai-harness"
_ADMIN_ACTOR = "operator@example.test"


async def _admin_plane_payloads(tmp_path: Path) -> str:
    """Drive every ADR-0142 admin route and return their joined response bodies.

    Two authenticated writes and the audit projection that answers for them. A
    mutation is the one place an operator's own string reaches a durable,
    hash-linked chain that is later served back, so it gets the same treatment
    ADR-0140's policy workspace did.
    """
    app = create_app(_settings(tmp_path), wall_clock=_NOW.timestamp)
    async with httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    ) as client:
        responses = [
            await client.patch(
                f"/control/v2/accounts/{_ADMIN_ACCOUNT}/state",
                headers=_AUTH,
                json={
                    "administrative_state": "draining",
                    "expected_revision": 0,
                    "actor": _ADMIN_ACTOR,
                },
            ),
            # Revision 1: the state change above is itself one link in the chain,
            # so a revoke composed against 0 would be refused as stale.
            await client.post(
                f"/control/v2/accounts/{_ADMIN_ACCOUNT}/revoke-leases",
                headers=_AUTH,
                json={"expected_revision": 1, "actor": _ADMIN_ACTOR},
            ),
            await client.get("/control/v2/accounts/audit", headers=_AUTH),
        ]
    # Checked before anything is scanned: a sweep over three 401 bodies would
    # find no credential and prove nothing, having never reached the write plane.
    assert [response.status_code for response in responses] == [200, 200, 200], [
        response.text for response in responses
    ]
    return "\n".join(response.text for response in responses)


@pytest.mark.parametrize(
    "credential",
    [
        pytest.param(_ANTHROPIC_KEY, id="the-anthropic-upstream-key"),
        pytest.param(_ZAI_KEY, id="the-zai-upstream-key-the-drained-account-uses"),
        pytest.param(_CONTROL_TOKEN, id="the-control-token-that-authorised-the-write"),
    ],
)
async def test_the_admin_plane_payloads_carry_no_credential(
    tmp_path: Path, credential: str
) -> None:
    """Draining an account names it; it never quotes what reaches it."""
    payload = await _admin_plane_payloads(tmp_path)

    assert credential not in payload


async def test_the_admin_plane_payloads_trip_no_canonical_secret_pattern(
    tmp_path: Path,
) -> None:
    """The repo's canonical detector (ADR-0085) finds nothing to redact."""
    payload = await _admin_plane_payloads(tmp_path)

    assert scan_for_secrets(payload) == []


@pytest.mark.parametrize(
    "published",
    [
        pytest.param(_ADMIN_ACCOUNT, id="the-account-id-both-mutations-named"),
        pytest.param(_ADMIN_ACTOR, id="the-actor-the-chain-attributes-them-to"),
    ],
)
async def test_the_admin_plane_publishes_what_it_is_meant_to(
    tmp_path: Path, published: str
) -> None:
    """The absence assertions are not vacuous: the audited join keys ARE present."""
    payload = await _admin_plane_payloads(tmp_path)

    assert published in payload
