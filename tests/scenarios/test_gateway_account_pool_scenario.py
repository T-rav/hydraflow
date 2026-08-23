"""MockWorld scenario: a pool falls back one hop, at the wire, without double-spend.

Everything on the path is real — the account registry compiled from a
server-owned document, the audited administrative overlay, the live capacity and
circuit state, the route-aware v2 mint, the virtual key store, the streaming
proxy and the ledger. Only the external origins are fakes, and they are an HTTP
transport that records which host it was actually asked for, so "the fallback
reached the second account" is a claim about the wire rather than about a mock's
call list.

The scenario asks the four questions #11540's acceptance criteria turn on, at the
external boundary rather than in a unit:

* does a hop actually move the *next* request to a different upstream host;
* does the gateway refuse to hop when its own terminal ledger has no qualifying
  failure to point at — no matter what the caller cites;
* is there ever a moment with two live leases for one dispatch;
* and does draining an account through the audited control plane stop it taking
  new leases while leaving the rest of the pool serving?
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit

import httpx
import pytest
from pydantic import SecretStr

from hydraflow_gateway.app import create_app
from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.ledger import GatewayBodyStore, GatewayLedger
from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

pytestmark = pytest.mark.scenario

_CONTROL_TOKEN = "pool-scenario-control-token-0123456789ab"
_PRIMARY_HOST = "zai-primary.test"
_SECONDARY_HOST = "zai-secondary.test"
_SECONDARY_ID = "zai-secondary"
_PRIMARY_ID = legacy_account_id(ProviderBinding.ZAI_HARNESS)
_MODEL = "glm-5.3"
_REPO = "acme/project-x"
_SLUG = "acme-project-x"

_ACCOUNTS_DOCUMENT = f"""
schema_version: 1
accounts:
  - id: {_SECONDARY_ID}
    display_name: z.ai secondary
    provider_binding: zai-harness
    base_url: https://{_SECONDARY_HOST}
    auth_style: bearer
    credential_env: GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY
    lease_capacity: 4
    request_capacity: 1
"""

_SSE_BODY = (
    b'event: message_start\ndata: {"type":"message_start","message":'
    b'{"model":"glm-5.3","usage":{"input_tokens":11}}}\n\n'
    b'event: message_stop\ndata: {"type":"message_stop"}\n\n'
)


class _FixedStream(httpx.AsyncByteStream):
    """A body the proxy streams, exactly as a real origin delivers one."""

    def __init__(self, payload: bytes) -> None:
        self._payload = payload

    async def __aiter__(self):  # noqa: ANN202 - httpx's own iterator protocol
        yield self._payload


class _PoolOrigin:
    """Two named upstreams behind one transport, one of which can be made to fail."""

    def __init__(self) -> None:
        self.hosts: list[str] = []
        self.rate_limited: set[str] = set()

    async def __call__(self, request: httpx.Request) -> httpx.Response:
        host = urlsplit(str(request.url)).netloc
        await request.aread()
        self.hosts.append(host)
        if host in self.rate_limited:
            # A real 429, forwarded verbatim: the proxy never retries it, and the
            # gateway's own ledger row is what a later attempt may cite. Streamed
            # rather than materialised, because the proxy streams every upstream
            # response and a pre-read body is not a shape it ever sees in life.
            return httpx.Response(
                429,
                headers={"content-type": "application/json"},
                stream=_FixedStream(b'{"error":"rate_limited"}'),
            )
        return httpx.Response(
            200,
            headers={"content-type": "text/event-stream"},
            stream=_FixedStream(_SSE_BODY),
        )


def _mint_body(attempt: str, **overrides: object) -> dict[str, object]:
    payload: dict[str, object] = {
        "mint_attempt_id": attempt,
        "dispatch_id": "pool-scenario-dispatch",
        "principal_kind": "spawn",
        "principal_id": "implementer",
        "spawn_id": "pool-scenario-spawn",
        "repo": _REPO,
        "repo_slug": _SLUG,
        "repo_class": "hydraflow",
        "worker_role": "implementer",
        "request_face": "agentic",
        "requirement_kind": "capability",
        "requirement_value": "balanced",
        "requested_model": "claude-sonnet-4-6",
        "effective_model": _MODEL,
        "route_decision_id": "dec_pool_scenario",
        "policy_id": "project-x-zai",
        "policy_revision": 1,
        "snapshot_hash": "sha256:pool",
        "capture_bodies": False,
        "ttl_seconds": 600,
    }
    payload.update(overrides)
    return payload


class _Pool:
    """One real gateway with a two-account z.ai pool, driven over HTTP."""

    def __init__(
        self, client: httpx.AsyncClient, origin: _PoolOrigin, app: Any
    ) -> None:
        self._client = client
        self.origin = origin
        self.app = app

    @property
    def auth(self) -> dict[str, str]:
        return {"authorization": f"Bearer {_CONTROL_TOKEN}"}

    async def mint(self, attempt: str, **overrides: object) -> dict[str, Any]:
        response = await self._client.post(
            "/control/v2/keys", headers=self.auth, json=_mint_body(attempt, **overrides)
        )
        response.raise_for_status()
        return dict(response.json())

    async def turn(self, token: str) -> int:
        """One real streaming turn on a minted credential. Returns its status."""
        async with self._client.stream(
            "POST",
            "/v1/messages",
            headers={
                "authorization": f"Bearer {token}",
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            content=json.dumps(
                {"model": _MODEL, "stream": True, "messages": []}
            ).encode(),
        ) as response:
            async for _chunk in response.aiter_bytes():
                pass
            return response.status_code

    async def revoke(self, key_id: str) -> None:
        response = await self._client.delete(
            f"/control/v1/keys/{key_id}", headers=self.auth
        )
        response.raise_for_status()

    async def accounts(self) -> dict[str, Any]:
        response = await self._client.get("/control/v2/accounts", headers=self.auth)
        response.raise_for_status()
        return dict(response.json())

    async def set_state(self, account_id: str, state: str, revision: int) -> int:
        response = await self._client.patch(
            f"/control/v2/accounts/{account_id}/state",
            headers=self.auth,
            json={
                "administrative_state": state,
                "expected_revision": revision,
                "actor": "operator@example.test",
            },
        )
        return response.status_code


@pytest.fixture
async def pool(  # noqa: ANN201 - the fixture's type is the helper
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    """A real gateway whose pool is compiled from a real accounts document."""
    # Exported BEFORE the app is built: an account's credential is resolved once,
    # at startup, exactly as a restart-required deployment fact should be.
    monkeypatch.setenv(
        "GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY", "pool-scenario-secondary-key"
    )
    accounts_file = tmp_path / "accounts.yaml"
    accounts_file.write_text(_ACCOUNTS_DOCUMENT, encoding="utf-8")
    settings = GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            ProviderBinding.ZAI_HARNESS: UpstreamSettings(
                base_url=f"https://{_PRIMARY_HOST}",
                api_key=SecretStr("pool-scenario-primary-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            )
        },
        accounts_file=accounts_file,
        account_state_dir=tmp_path / "account-state",
        ledger_path=tmp_path / "requests.jsonl",
        body_dir=tmp_path / "bodies",
        max_fallback_hops=1,
    )
    origin = _PoolOrigin()
    upstream_client = httpx.AsyncClient(transport=httpx.MockTransport(origin))
    app = create_app(
        settings,
        key_store=VirtualKeyStore(max_ttl_seconds=settings.max_key_ttl_seconds),
        client=upstream_client,
        ledger=GatewayLedger(settings.ledger_path),
        body_store=GatewayBodyStore(settings.body_dir),
    )
    gateway = httpx.AsyncClient(
        transport=httpx.ASGITransport(app=app), base_url="http://gateway.test"
    )
    try:
        async with app.router.lifespan_context(app):
            yield _Pool(gateway, origin, app)
    finally:
        await gateway.aclose()
        await upstream_client.aclose()


async def _hop(pool: _Pool) -> tuple[dict[str, Any], dict[str, Any]]:
    """Drive one rate-limited turn on the primary, then one licensed hop."""
    pool.origin.rate_limited.add(_PRIMARY_HOST)
    first = await pool.mint("attempt-1")
    await pool.turn(str(first["token"]))
    await pool.revoke(str(first["key_id"]))
    second = await pool.mint(
        "attempt-2",
        retry_of_mint_decision_id=first["decision"]["mint_decision_id"],
    )
    return first, second


async def test_the_first_attempt_selects_the_primary_account(pool: _Pool) -> None:
    first = await pool.mint("attempt-1")

    assert first["decision"]["account_id"] == _PRIMARY_ID


async def test_a_licensed_hop_selects_the_second_account(pool: _Pool) -> None:
    _first, second = await _hop(pool)

    assert second["decision"]["account_id"] == _SECONDARY_ID


async def test_a_hop_reaches_the_second_account_at_the_wire(pool: _Pool) -> None:
    """The claim this scenario exists for: a different host actually served it."""
    _first, second = await _hop(pool)
    await pool.turn(str(second["token"]))

    assert pool.origin.hosts == [_PRIMARY_HOST, _SECONDARY_HOST]


async def test_a_hop_never_leaves_two_live_leases(pool: _Pool) -> None:
    _first, second = await _hop(pool)
    del second
    accounts = await pool.accounts()

    assert sum(account["lease_count"] for account in accounts["accounts"]) == 1


async def test_a_hop_is_refused_while_the_prior_lease_is_still_held(
    pool: _Pool,
) -> None:
    """Revoke-then-remint at the wire: no hop until the prior key is given back."""
    pool.origin.rate_limited.add(_PRIMARY_HOST)
    first = await pool.mint("attempt-1")
    await pool.turn(str(first["token"]))

    second = await pool.mint(
        "attempt-2",
        retry_of_mint_decision_id=first["decision"]["mint_decision_id"],
    )

    assert second["decision"]["reason"] == "fallback-lease-still-held"


async def test_a_hop_is_refused_when_the_gateway_saw_no_qualifying_failure(
    pool: _Pool,
) -> None:
    """Caller-supplied error text has no authority; the gateway's ledger does."""
    first = await pool.mint("attempt-1")
    await pool.turn(str(first["token"]))
    await pool.revoke(str(first["key_id"]))

    second = await pool.mint(
        "attempt-2",
        retry_of_mint_decision_id=first["decision"]["mint_decision_id"],
    )

    assert second["decision"]["reason"] == "fallback-not-authorised"


async def test_an_unlicensed_hop_issues_no_credential(pool: _Pool) -> None:
    first = await pool.mint("attempt-1")
    await pool.turn(str(first["token"]))
    await pool.revoke(str(first["key_id"]))

    second = await pool.mint(
        "attempt-2",
        retry_of_mint_decision_id=first["decision"]["mint_decision_id"],
    )

    assert second["token"] is None


async def test_the_hop_ceiling_stops_the_second_hop(pool: _Pool) -> None:
    """``max_fallback_hops=1``, so a second qualifying failure buys nothing."""
    pool.origin.rate_limited.update({_PRIMARY_HOST, _SECONDARY_HOST})
    _first, second = await _hop(pool)
    await pool.turn(str(second["token"]))
    await pool.revoke(str(second["key_id"]))

    third = await pool.mint(
        "attempt-3",
        retry_of_mint_decision_id=second["decision"]["mint_decision_id"],
    )

    assert third["decision"]["reason"] == "fallback-budget-exhausted"


async def test_draining_an_account_hands_the_lane_to_the_rest_of_the_pool(
    pool: _Pool,
) -> None:
    assert await pool.set_state(_PRIMARY_ID, "draining", 0) == 200
    minted = await pool.mint("attempt-drained")

    assert minted["decision"]["account_id"] == _SECONDARY_ID


async def test_a_stale_administrative_edit_is_refused(pool: _Pool) -> None:
    """An old browser tab must not be able to undo an emergency drain."""
    await pool.set_state(_PRIMARY_ID, "draining", 0)

    assert await pool.set_state(_PRIMARY_ID, "enabled", 0) == 409


async def test_the_accounts_view_publishes_the_pool_it_actually_has(
    pool: _Pool,
) -> None:
    accounts = await pool.accounts()

    assert [account["account_id"] for account in accounts["accounts"]] == sorted(
        {legacy_account_id(ProviderBinding.ANTHROPIC), _PRIMARY_ID, _SECONDARY_ID}
    )


async def test_the_accounts_view_publishes_a_declared_capacity(pool: _Pool) -> None:
    accounts = await pool.accounts()
    declared = next(
        account
        for account in accounts["accounts"]
        if account["account_id"] == _SECONDARY_ID
    )

    assert declared["lease_capacity"] == 4


async def test_a_legacy_account_publishes_no_invented_ceiling(pool: _Pool) -> None:
    """``None``, not zero: a rendered "0 of 0" would be a limit nobody set."""
    accounts = await pool.accounts()
    legacy = next(
        account
        for account in accounts["accounts"]
        if account["account_id"] == _PRIMARY_ID
    )

    assert legacy["lease_capacity"] is None


async def test_the_gateways_own_capacity_refusal_never_opens_a_circuit(
    pool: _Pool,
) -> None:
    """A 429 the gateway wrote itself is not evidence about the upstream.

    Feeding an admission decision back in as passive health evidence is how a
    saturated account manufactures its own outage: three refusals would trip a
    circuit that then also refuses new leases. The secondary account declares
    ``request_capacity: 1``, and its one slot is taken here by a stand-in for
    another in-flight request, so all three turns below are refused by the
    gateway and none of them ever reaches an origin.
    """
    await pool.set_state(_PRIMARY_ID, "draining", 0)
    minted = await pool.mint("attempt-capacity")
    token = str(minted["token"])
    pool.app.state.gateway_account_state.reserve_request(
        _SECONDARY_ID, holder="another-in-flight-request"
    )

    statuses = [await pool.turn(token) for _ in range(3)]
    accounts = await pool.accounts()
    served = next(
        account
        for account in accounts["accounts"]
        if account["account_id"] == _SECONDARY_ID
    )

    assert (statuses, served["circuit_state"]) == ([429, 429, 429], "closed")


async def test_a_capacity_refusal_sends_no_upstream_bytes(pool: _Pool) -> None:
    """The refusal is admission control, so nothing was asked of any account."""
    await pool.set_state(_PRIMARY_ID, "draining", 0)
    minted = await pool.mint("attempt-capacity")
    pool.app.state.gateway_account_state.reserve_request(
        _SECONDARY_ID, holder="another-in-flight-request"
    )

    await pool.turn(str(minted["token"]))

    assert pool.origin.hosts == []


async def test_a_real_upstream_failure_does_open_the_circuit(pool: _Pool) -> None:
    """The contrast, so the exclusion above is not passing for a second reason."""
    pool.origin.rate_limited.add(_PRIMARY_HOST)
    minted = await pool.mint("attempt-real-429")
    token = str(minted["token"])
    for _ in range(3):
        await pool.turn(token)
    accounts = await pool.accounts()
    served = next(
        account
        for account in accounts["accounts"]
        if account["account_id"] == _PRIMARY_ID
    )

    assert served["circuit_state"] == "open"
