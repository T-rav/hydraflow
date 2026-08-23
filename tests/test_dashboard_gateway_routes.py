"""Dashboard proxy for the gateway's account and route plane.

Two planes in one file, deliberately: the ungated reads (#11534, ADR-0138) and
the two host-admin writes (#11540, ADR-0142) that spend ADR-0138 §D5's
precondition. The write tests exist to pin three things that are easy to get
subtly wrong — the gate refusing before it authenticates, the gateway's own
optimistic-concurrency refusal surviving the proxy with its status intact, and
the recorded ``actor`` coming from the authenticated boundary rather than from
anything a browser sent.
"""

from __future__ import annotations

from collections.abc import AsyncIterator
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import SecretStr

from dashboard_routes._gateway_routes import build_gateway_router
from gateway_control_reader import GatewayControlReader, GatewayControlWriter
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
from operator_identity import OPERATOR_ID_ENV, OPERATOR_TOKEN_ENV
from tests.helpers import ConfigFactory, make_dashboard_router

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)

_OPERATOR_TOKEN = "hfop_" + "t" * 40
_OPERATOR_ID = "travis"
_ENV = {OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN, OPERATOR_ID_ENV: _OPERATOR_ID}
_AUTH = {"Authorization": f"Bearer {_OPERATOR_TOKEN}"}

_ZAI_ACCOUNT = "legacy-zai-harness"
_STATE_ROUTE = f"/api/gateway/accounts/{_ZAI_ACCOUNT}/state"
_REVOKE_ROUTE = f"/api/gateway/accounts/{_ZAI_ACCOUNT}/revoke-leases"


class _EmptyStream(httpx.AsyncByteStream):
    async def __aiter__(self) -> AsyncIterator[bytes]:
        return
        yield b""

    async def aclose(self) -> None:
        return None


def _gateway_settings(tmp_path: Path) -> GatewaySettings:
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url="https://zai.test/api/anthropic",
                api_key=SecretStr("real-zai-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            )
        },
        ledger_path=tmp_path / "gateway.jsonl",
        body_dir=tmp_path / "bodies",
        # Under tmp_path on purpose: the default is a RELATIVE path, so leaving
        # it would have every run of this file append to a hash chain inside the
        # working copy — and the revision each test composes against would then
        # depend on how many times the suite had run before.
        account_state_dir=tmp_path / "accounts",
    )


def _row(request_id: str) -> GatewayLedgerRow:
    return GatewayLedgerRow(
        request_id=request_id,
        key_id="key-1",
        principal={
            "kind": "spawn",
            "id": "implementer",
            "spawn_id": "spawn-1",
            "issue_number": 11534,
        },
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        body_capture_policy="metadata-only",
        timestamp=_NOW,
        latency_ms=12.0,
        status_code=200,
        status=GatewayRequestStatus.COMPLETED,
        upstream_provider=ProviderBinding.ZAI_HARNESS,
        path="/v1/messages",
        model_requested="glm-5.2",
        model_served="glm-5.3",
        completed=True,
        client_aborted=False,
        usage_complete=True,
        cost_usd=0.25,
        cost_unknown=False,
    )


def _live_gateway(tmp_path: Path, *, principal_id: str = "implementer") -> FastAPI:
    """Build a real gateway app with one lease, one in-flight, one terminal route."""
    store = VirtualKeyStore(max_ttl_seconds=600, id_factory=lambda: "key-1")
    minted = store.mint(
        MintKeyRequest(
            principal_kind="spawn",
            principal_id=principal_id,
            spawn_id="spawn-1",
            session_id="session-1",
            issue_number=11534,
            repo_slug="acme/hydraflow",
            repo_class=RepoClass.HYDRAFLOW,
            provider_binding=ProviderBinding.ZAI_HARNESS,
            capture_bodies=False,
            ttl_seconds=300,
        )
    )
    identity = store.resolve(minted.token)
    registry = ActiveRouteRegistry(started_at=_NOW)
    registry.register(
        request_id="req-live", identity=identity, path="/v1/messages", started_at=_NOW
    )
    registry.register(
        request_id="req-done", identity=identity, path="/v1/messages", started_at=_NOW
    )
    registry.release(_row("req-done"))

    async def upstream(_: httpx.Request) -> httpx.Response:
        return httpx.Response(200, stream=_EmptyStream())

    return create_app(
        _gateway_settings(tmp_path),
        key_store=store,
        client=httpx.AsyncClient(transport=httpx.MockTransport(upstream)),
        active_routes=registry,
        wall_clock=_NOW.timestamp,
    )


def _dashboard(
    tmp_path: Path,
    *,
    gateway: FastAPI | None = None,
    control_token: str = _CONTROL_TOKEN,
    unreachable: bool = False,
    principal_id: str = "implementer",
    host: str = "127.0.0.1",
    workspace_enabled: bool = True,
    env: dict[str, str] | None = None,
) -> TestClient:
    config = ConfigFactory.create(dashboard_host=host)
    object.__setattr__(config, "gateway_policy_workspace_enabled", workspace_enabled)
    resolved = gateway or _live_gateway(tmp_path, principal_id=principal_id)

    def client_factory() -> httpx.AsyncClient:
        if unreachable:

            async def dead(_: httpx.Request) -> httpx.Response:
                raise httpx.ConnectError("gateway down")

            return httpx.AsyncClient(transport=httpx.MockTransport(dead))
        return httpx.AsyncClient(transport=httpx.ASGITransport(app=resolved))

    def reader_factory() -> GatewayControlReader:
        return GatewayControlReader(
            base_url="http://gateway.test",
            control_token=control_token,
            client_factory=client_factory,
        )

    def writer_factory() -> GatewayControlWriter:
        return GatewayControlWriter(
            base_url="http://gateway.test",
            control_token=control_token,
            client_factory=client_factory,
        )

    app = FastAPI()
    app.include_router(
        build_gateway_router(
            config,
            reader_factory=reader_factory,
            writer_factory=writer_factory,
            env=_ENV if env is None else env,
        )
    )
    return TestClient(app)


def _mutate(
    client: TestClient,
    route: str,
    *,
    body: dict[str, Any] | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    """Send one host-admin mutation on whichever of the two routes is named."""
    payload = body if body is not None else {"expected_revision": 0}
    if route == _STATE_ROUTE:
        payload = {"administrative_state": "draining", **payload}
        return client.patch(route, json=payload, headers=headers)
    return client.post(route, json=payload, headers=headers)


def test_accounts_route_returns_the_gateway_account_inventory(tmp_path: Path) -> None:
    """The dashboard surfaces the gateway's compiled account identities."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").json()

    assert [account["account_id"] for account in body["data"]["accounts"]] == [
        "legacy-anthropic",
        "legacy-zai-harness",
    ]


def test_accounts_route_marks_an_available_source(tmp_path: Path) -> None:
    """A successful read is explicitly labelled available."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").json()

    assert body["available"] is True


def test_accounts_route_forwards_the_requested_window(tmp_path: Path) -> None:
    """The operator's window reaches the gateway rather than being ignored."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts?window_seconds=600").json()

    assert body["data"]["window_seconds"] == 600


@pytest.mark.parametrize(
    ("url", "status"),
    [
        pytest.param(
            "/api/gateway/accounts?window_seconds=0",
            422,
            id="an-out-of-range-health-window-is-refused",
        ),
        pytest.param(
            "/api/gateway/routes/recent?limit=100000",
            422,
            id="an-unbounded-route-page-is-refused",
        ),
        pytest.param(
            "/api/gateway/accounts/audit?limit=100000",
            422,
            id="an-unbounded-history-page-is-refused",
        ),
        pytest.param(
            "/api/gateway/accounts/audit",
            200,
            id="the-audit-read-needs-no-operator-credential",
        ),
    ],
)
def test_the_read_plane_bounds_its_inputs_and_gates_none_of_them(
    tmp_path: Path, url: str, status: int
) -> None:
    """The proxy bounds its own queries — and gates none of its reads.

    A page-size ceiling keeps a dashboard poll from becoming a scan, and the
    bounds are the gateway's own so a stale copy cannot 422 every poll. The
    audit read is in the same table on purpose: seeing the administrative
    overlay is not changing it, so it answers without a credential.
    """
    assert _dashboard(tmp_path).get(url).status_code == status


def _dig(payload: object, keys: tuple[str | int, ...]) -> object:
    """Walk a nested JSON payload by key/index path."""
    current = payload
    for key in keys:
        current = current[key]  # type: ignore[index]
    return current


@pytest.mark.parametrize(
    ("endpoint", "keys", "expected"),
    [
        pytest.param(
            "/api/gateway/routes/active",
            ("leases", 0, "account_id"),
            "legacy-zai-harness",
            id="a-minted-key-is-a-lease-on-its-bound-account",
        ),
        pytest.param(
            "/api/gateway/routes/active",
            ("in_flight", 0, "request_id"),
            "req-live",
            id="a-streaming-request-is-reported-separately-from-leases",
        ),
        pytest.param(
            "/api/gateway/routes/active",
            ("in_flight", 0, "worker_role"),
            "implementer",
            id="a-catalog-principal-gets-the-adr-0137-role-join",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "model_requested"),
            "glm-5.2",
            id="a-terminal-route-keeps-the-requested-model",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "model_served"),
            "glm-5.3",
            id="a-terminal-route-keeps-the-served-model",
        ),
        pytest.param(
            "/api/gateway/routes/recent",
            ("routes", 0, "status"),
            "completed",
            id="a-terminal-route-keeps-its-status",
        ),
    ],
)
def test_live_view_column_is_proxied_through_unchanged(
    tmp_path: Path, endpoint: str, keys: tuple[str | int, ...], expected: object
) -> None:
    """Each column the Live view reads reaches the dashboard from the gateway."""
    body = _dashboard(tmp_path).get(endpoint).json()

    assert _dig(body["data"], keys) == expected


def test_active_routes_leave_an_unmapped_principal_unroled(tmp_path: Path) -> None:
    """A loop name is not a worker role, and is never guessed into one."""
    client = _dashboard(tmp_path, principal_id="adr_review")
    body = client.get("/api/gateway/routes/active").json()

    assert body["data"]["in_flight"][0]["worker_role"] is None


def test_the_dashboard_router_actually_mounts_the_gateway_routes(
    config: object, event_bus: object, state: object, tmp_path: Path
) -> None:
    """The real ``create_router`` wiring, not just the router built in isolation."""
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

    paths = {getattr(route, "path", "") for route in router.routes}

    assert "/api/gateway/accounts" in paths


def test_unreachable_gateway_still_answers_with_2xx(tmp_path: Path) -> None:
    """The panel renders a degraded state rather than a browser-level error."""
    response = _dashboard(tmp_path, unreachable=True).get("/api/gateway/accounts")

    assert response.status_code == 200


def test_dashboard_response_never_carries_the_control_token(tmp_path: Path) -> None:
    """The browser must not be able to read the gateway control credential."""
    body = _dashboard(tmp_path).get("/api/gateway/routes/active").text

    assert _CONTROL_TOKEN not in body


def test_dashboard_response_never_carries_an_upstream_provider_key(
    tmp_path: Path,
) -> None:
    """No provider secret crosses the proxy boundary."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").text

    assert "real-zai-key" not in body


# --------------------------------------------------------------------------
# ADR-0142 pool facts on the read plane
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("field", "expected"),
    [
        pytest.param("lease_capacity", None, id="an-undeclared-lease-ceiling-is-null"),
        pytest.param(
            "request_capacity", None, id="an-undeclared-request-ceiling-is-null"
        ),
        pytest.param("circuit_state", "closed", id="an-untripped-breaker-is-closed"),
        pytest.param(
            "circuit_consecutive_failures", 0, id="a-quiet-account-has-no-failures"
        ),
        pytest.param("circuit_reset_at", None, id="a-closed-breaker-has-no-reset-time"),
        pytest.param(
            "circuit_last_condition", None, id="a-closed-breaker-names-no-condition"
        ),
    ],
)
def test_pool_facts_reach_the_dashboard_for_a_legacy_account(
    tmp_path: Path, field: str, expected: object
) -> None:
    """A legacy account declares no ceiling, and the proxy publishes that as null."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts").json()

    assert body["data"]["accounts"][0][field] == expected


# --------------------------------------------------------------------------
# ADR-0138 §D5 — the gate the host-admin writes spend
# --------------------------------------------------------------------------


@pytest.mark.parametrize("route", [_STATE_ROUTE, _REVOKE_ROUTE])
@pytest.mark.parametrize(
    ("kwargs", "headers", "status", "code"),
    [
        pytest.param(
            {"host": "0.0.0.0"},  # noqa: S104 — the bind under test
            _AUTH,
            403,
            "dashboard-not-loopback",
            id="a-valid-operator-token-cannot-write-past-a-non-loopback-bind",
        ),
        pytest.param(
            {"workspace_enabled": False},
            _AUTH,
            403,
            "workspace-disabled",
            id="the-kill-switch-closes-the-write-plane-outright",
        ),
        pytest.param(
            {"env": {}},
            _AUTH,
            403,
            "no-operator-identity",
            id="no-configured-operator-credential-is-not-an-open-gate",
        ),
        pytest.param(
            {},
            None,
            401,
            "unauthenticated-operator",
            id="an-open-gate-still-needs-a-presented-credential",
        ),
        pytest.param(
            {},
            {"Authorization": "Bearer hfop_wrong"},
            401,
            "unauthenticated-operator",
            id="a-wrong-credential-authenticates-nobody",
        ),
    ],
)
def test_a_host_admin_mutation_is_refused_at_the_write_boundary(
    tmp_path: Path,
    route: str,
    kwargs: dict[str, Any],
    headers: dict[str, str] | None,
    status: int,
    code: str,
) -> None:
    """Both mutations refuse identically, and the bind is reported before the token."""
    response = _mutate(_dashboard(tmp_path, **kwargs), route, headers=headers)

    assert (response.status_code, response.json()["code"]) == (status, code)


def test_a_refused_mutation_changes_nothing_on_the_gateway(tmp_path: Path) -> None:
    """A 403 is total: no revision is burned by a request that never authenticated."""
    client = _dashboard(tmp_path, host="0.0.0.0")  # noqa: S104 — the bind under test

    _mutate(client, _STATE_ROUTE, headers=_AUTH)

    assert client.get("/api/gateway/accounts/audit").json()["data"]["revision"] == 0


# --------------------------------------------------------------------------
# The authenticated happy path
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("route", "field", "expected"),
    [
        pytest.param(
            _STATE_ROUTE,
            "administrative_state",
            "draining",
            id="draining-an-account-returns-the-state-that-landed",
        ),
        pytest.param(
            _STATE_ROUTE, "revision", 1, id="a-state-change-advances-the-revision"
        ),
        pytest.param(
            _STATE_ROUTE, "actor", _OPERATOR_ID, id="a-state-change-names-the-operator"
        ),
        pytest.param(
            # An unbound v1 key names a lane, not an account, so an
            # account-scoped revocation must not end it as collateral — and the
            # proxy reports the empty list honestly rather than a count it wishes
            # it had.
            _REVOKE_ROUTE,
            "revoked_key_ids",
            [],
            id="revoking-reports-only-the-route-bound-keys-it-actually-ended",
        ),
        pytest.param(
            _REVOKE_ROUTE, "revision", 1, id="a-revocation-advances-the-revision"
        ),
        pytest.param(
            _REVOKE_ROUTE, "actor", _OPERATOR_ID, id="a-revocation-names-the-operator"
        ),
    ],
)
def test_an_authenticated_operator_administers_an_account(
    tmp_path: Path, route: str, field: str, expected: object
) -> None:
    """The gate open and a credential presented, the mutation commits and says so."""
    response = _mutate(_dashboard(tmp_path), route, headers=_AUTH)

    assert response.json()[field] == expected


def test_a_committed_state_change_is_visible_on_the_next_accounts_read(
    tmp_path: Path,
) -> None:
    """The write and the read describe the same overlay, not two copies of one."""
    client = _dashboard(tmp_path)

    _mutate(client, _STATE_ROUTE, headers=_AUTH)
    accounts = client.get("/api/gateway/accounts").json()["data"]["accounts"]

    assert [a["administrative_state"] for a in accounts] == ["enabled", "draining"]


# --------------------------------------------------------------------------
# Provenance: the actor is the boundary's, never the caller's
# --------------------------------------------------------------------------


@pytest.mark.parametrize("route", [_STATE_ROUTE, _REVOKE_ROUTE])
def test_a_caller_supplied_actor_is_refused_rather_than_recorded(
    tmp_path: Path, route: str
) -> None:
    """The body cannot claim provenance: there is no actor field to claim it with."""
    response = _mutate(
        _dashboard(tmp_path),
        route,
        body={"expected_revision": 0, "actor": "somebody-else"},
        headers=_AUTH,
    )

    assert response.status_code == 422


@pytest.mark.parametrize("route", [_STATE_ROUTE, _REVOKE_ROUTE])
def test_the_recorded_actor_comes_from_the_authenticated_identity(
    tmp_path: Path, route: str
) -> None:
    """What lands on the gateway's audit chain is HYDRAFLOW_OPERATOR_ID, full stop."""
    client = _dashboard(tmp_path)

    _mutate(client, route, headers=_AUTH)
    entries = client.get("/api/gateway/accounts/audit").json()["data"]["entries"]

    assert [entry["actor"] for entry in entries] == [_OPERATOR_ID]


def test_an_unnamed_operator_is_recorded_under_the_default_label(
    tmp_path: Path,
) -> None:
    """A deployment that authenticated an operator but named none still has provenance."""
    client = _dashboard(tmp_path, env={OPERATOR_TOKEN_ENV: _OPERATOR_TOKEN})

    _mutate(client, _STATE_ROUTE, headers=_AUTH)
    entries = client.get("/api/gateway/accounts/audit").json()["data"]["entries"]

    assert entries[0]["actor"] == "operator"


# --------------------------------------------------------------------------
# The gateway's own refusals, passed through rather than reinterpreted
# --------------------------------------------------------------------------


@pytest.mark.parametrize("route", [_STATE_ROUTE, _REVOKE_ROUTE])
def test_a_stale_revision_surfaces_as_the_gateway_s_409(
    tmp_path: Path, route: str
) -> None:
    """A lost update is a 409 an operator can act on, not a generic failure."""
    client = _dashboard(tmp_path)
    _mutate(client, _STATE_ROUTE, headers=_AUTH)  # the overlay moves to revision 1

    response = _mutate(client, route, body={"expected_revision": 0}, headers=_AUTH)

    assert (response.status_code, response.json()["code"]) == (409, "stale-revision")


def test_a_stale_mutation_tells_the_operator_to_reload(tmp_path: Path) -> None:
    """The 409's detail names the action, because "conflict" is not an instruction."""
    client = _dashboard(tmp_path)
    _mutate(client, _STATE_ROUTE, headers=_AUTH)

    response = _mutate(client, _STATE_ROUTE, headers=_AUTH)

    assert "reload" in response.json()["detail"]


@pytest.mark.parametrize(
    ("route", "method"),
    [
        pytest.param("/state", "PATCH", id="setting-state-on-a-phantom-account"),
        pytest.param(
            "/revoke-leases", "POST", id="revoking-leases-on-a-phantom-account"
        ),
    ],
)
def test_an_unknown_account_surfaces_as_the_gateway_s_404(
    tmp_path: Path, route: str, method: str
) -> None:
    """An account the gateway does not compile is a 404, never an invented one."""
    client = _dashboard(tmp_path)
    body: dict[str, Any] = {"expected_revision": 0}
    if method == "PATCH":
        body["administrative_state"] = "disabled"

    response = client.request(
        method,
        f"/api/gateway/accounts/no-such-account{route}",
        json=body,
        headers=_AUTH,
    )

    assert (response.status_code, response.json()["code"]) == (404, "unknown-account")


def test_an_unreachable_gateway_never_reports_a_mutation_as_failed(
    tmp_path: Path,
) -> None:
    """Nobody knows whether it committed, so the answer is 502 "re-read", not 4xx."""
    client = _dashboard(tmp_path, unreachable=True)

    response = _mutate(client, _STATE_ROUTE, headers=_AUTH)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "gateway-unreachable",
    )


def test_a_control_credential_failure_is_never_relayed_as_the_operator_s(
    tmp_path: Path,
) -> None:
    """A 401 on THIS proxy's gateway token must not read as the operator's fault."""
    client = _dashboard(tmp_path, control_token="wrong-gateway-control-token")

    response = _mutate(client, _STATE_ROUTE, headers=_AUTH)

    assert (response.status_code, response.json()["code"]) == (
        502,
        "gateway-unreachable",
    )


def test_a_mutation_response_never_carries_the_control_token(tmp_path: Path) -> None:
    """The write path is held to the read path's secrecy contract."""
    body = _mutate(_dashboard(tmp_path), _STATE_ROUTE, headers=_AUTH).text

    assert _CONTROL_TOKEN not in body and _OPERATOR_TOKEN not in body


# --------------------------------------------------------------------------
# The audit read
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("kwargs", "key", "expected"),
    [
        pytest.param(
            {}, "editable", True, id="a-loopback-bind-with-a-token-is-editable"
        ),
        pytest.param({}, "write_gate", "enabled", id="an-open-gate-says-so"),
        pytest.param(
            {"host": "0.0.0.0"},  # noqa: S104 — the bind under test
            "editable",
            False,
            id="a-non-loopback-bind-is-never-editable",
        ),
        pytest.param(
            {"host": "0.0.0.0"},  # noqa: S104 — the bind under test
            "write_gate",
            "dashboard-not-loopback",
            id="a-closed-gate-names-the-reason-the-console-must-render",
        ),
    ],
)
def test_the_audit_read_publishes_the_write_gate(
    tmp_path: Path, kwargs: dict[str, Any], key: str, expected: object
) -> None:
    """The console learns the gate from a read, not from a click that would 403."""
    body = _dashboard(tmp_path, **kwargs).get("/api/gateway/accounts/audit").json()

    assert body[key] == expected


def test_the_audit_read_publishes_a_verified_chain(tmp_path: Path) -> None:
    """`chain_verified` is stated rather than assumed, and an empty chain verifies."""
    body = _dashboard(tmp_path).get("/api/gateway/accounts/audit").json()

    assert body["data"]["chain_verified"] is True


def test_the_dashboard_router_mounts_the_host_admin_write_routes(
    config: object, event_bus: object, state: object, tmp_path: Path
) -> None:
    """The real ``create_router`` wiring, not just the router built in isolation."""
    router, _ = make_dashboard_router(config, event_bus, state, tmp_path)

    paths = {getattr(route, "path", "") for route in router.routes}

    assert {
        "/api/gateway/accounts/{account_id}/state",
        "/api/gateway/accounts/{account_id}/revoke-leases",
        "/api/gateway/accounts/audit",
    } <= paths
