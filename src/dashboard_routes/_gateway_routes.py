"""Gateway account and route proxy routes (ADR-0138 #11534, ADR-0142 #11540).

Four reads and two writes under ``/api/gateway``. The dashboard backend holds
the env-only control credential and returns only the gateway's already-sanitized
models, so the browser never receives a gateway control token and no provider
secret crosses this boundary.

**The reads are ungated**, as they have been since P0: accounts, the two route
views, and the administrative audit chain. None of them can change anything, and
an operator who cannot see the overlay cannot reason about it.

**The two writes spend ADR-0138 §D5's precondition, and spend it exactly the way
``_gateway_policy_routes`` does.** Every mutation here:

* refuses unless ``operator_identity.write_gate`` returns ``ENABLED`` — the kill
  switch is off, the dashboard is bound to loopback, and an operator credential
  is configured. The bind is checked **before** the credential, because a valid
  token cannot make a shared socket safe and the bind is what an operator has to
  fix first;
* refuses unless ``authenticate_operator`` proves an identity from the
  ``Authorization`` header; and
* records **that identity** as the gateway audit chain's ``actor``. The request
  bodies below forbid extra fields and declare no actor, so a caller that tries
  to name one gets a 422 rather than a mutation attributed to a string it chose.

Refusals from the gateway's own optimistic-concurrency check pass through with
their status intact — 409 stale revision, 404 unknown account, 503 broken audit
chain — because those are the operator's answers, not this proxy's.
"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from fastapi import APIRouter, Query, Request
from pydantic import BaseModel, ConfigDict, Field
from starlette.responses import JSONResponse

from gateway_control_reader import (
    DEFAULT_ACCOUNT_AUDIT_LIMIT,
    DEFAULT_ACCOUNT_WINDOW_SECONDS,
    DEFAULT_RECENT_LIMIT,
    GatewayControlReader,
    GatewayControlWriter,
    GatewayWriteResult,
    GatewayWriteState,
    reader_from_config,
    writer_from_config,
)

# Bounds are borrowed from the gateway's own read plane, never re-declared here:
# a proxy that validated against a stale copy would turn every poll into a 422
# the operator would read as "gateway unreachable".
from hydraflow_gateway.accounts import (
    MAX_HEALTH_WINDOW_SECONDS,
    MIN_HEALTH_WINDOW_SECONDS,
    AdministrativeState,
)
from hydraflow_gateway.active_routes import MAX_RECENT_LIMIT
from hydraflow_gateway.routing_account_admin import MAX_HISTORY_LIMIT
from operator_identity import WriteGate, authenticate_operator, write_gate

if TYPE_CHECKING:
    from collections.abc import Callable

    from config import HydraFlowConfig

_GATE_DETAIL: dict[WriteGate, str] = {
    WriteGate.WORKSPACE_DISABLED: (
        "the operator write plane is switched off (gateway_policy_workspace_enabled)"
    ),
    WriteGate.DASHBOARD_NOT_LOOPBACK: (
        "account administration is disabled while the dashboard is bound beyond "
        "loopback; there is no operator authorization boundary on a shared "
        "socket (ADR-0138 D5)"
    ),
    WriteGate.NO_OPERATOR_IDENTITY: (
        "account administration needs an authenticated operator identity; set "
        "HYDRAFLOW_OPERATOR_TOKEN on the dashboard host"
    ),
}

#: What an operator should do about each non-refusal outcome, as a code plus the
#: status that describes whose problem it is. A write whose transport died is
#: 502 and says so; it is never reported as a failed mutation, because nobody
#: knows whether it committed.
_WRITE_FAILURE: dict[GatewayWriteState, tuple[int, str, str]] = {
    GatewayWriteState.NOT_CONFIGURED: (
        503,
        "gateway-not-configured",
        "no gateway control token or base URL is configured on this dashboard, "
        "so there is no control plane to administer",
    ),
    GatewayWriteState.UNREACHABLE: (
        502,
        "gateway-unreachable",
        "the gateway did not answer this mutation; re-read the accounts view "
        "before retrying, because it may still have been applied",
    ),
    GatewayWriteState.INVALID: (
        502,
        "gateway-invalid-response",
        "the gateway answered with an unrecognised payload; refusing to report "
        "a mutation this dashboard could not verify",
    ),
}

_UNNAMED_REFUSAL = "gateway-refused"
"""A refusal whose code this build does not recognise. Reported, never echoed."""


class AccountStateBody(BaseModel):
    """Body for ``PATCH /api/gateway/accounts/{account_id}/state``.

    No ``actor`` field, and ``extra="forbid"``: provenance comes from the
    authenticated operator boundary, so a body that tries to claim one is a 422
    rather than a mutation recorded under a name the caller picked.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    administrative_state: AdministrativeState
    expected_revision: int = Field(ge=0)


class RevokeLeasesBody(BaseModel):
    """Body for ``POST /api/gateway/accounts/{account_id}/revoke-leases``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    expected_revision: int = Field(ge=0)


def build_gateway_router(
    config: HydraFlowConfig,
    *,
    reader_factory: Callable[[], GatewayControlReader] | None = None,
    writer_factory: Callable[[], GatewayControlWriter] | None = None,
    env: dict[str, str] | None = None,
) -> APIRouter:
    """Build the ``/api/gateway`` account and route router.

    *reader_factory* / *writer_factory* are the injectable transport boundary:
    production builds them from *config* plus ``HYDRAFLOW_GATEWAY_CONTROL_TOKEN``;
    tests supply clients pointed at an in-process gateway app. *env* is the
    injectable operator-credential boundary, mirroring
    ``_gateway_policy_routes``: production reads the real environment.
    """

    router = APIRouter(prefix="/api/gateway", tags=["gateway"])

    def _reader() -> GatewayControlReader:
        if reader_factory is not None:
            return reader_factory()
        return reader_from_config(config)

    def _writer() -> GatewayControlWriter:
        if writer_factory is not None:
            return writer_factory()
        return writer_from_config(config)

    def _authorize(request: Request) -> tuple[str, JSONResponse | None]:
        """Return the authenticated actor, or the refusal to answer instead."""
        gate = write_gate(config, env=env)
        if gate is not WriteGate.ENABLED:
            # Before authentication on purpose: a credential cannot make a
            # non-loopback bind safe, and saying so is the actionable answer.
            return "", _error(403, gate.value, _GATE_DETAIL[gate])
        identity = authenticate_operator(request.headers.get("authorization"), env=env)
        if identity is None:
            return "", JSONResponse(
                {
                    "code": "unauthenticated-operator",
                    "detail": (
                        "present the operator bearer token to administer accounts"
                    ),
                },
                status_code=401,
                headers={"WWW-Authenticate": "Bearer"},
            )
        return identity.actor, None

    @router.get("/accounts")
    async def read_accounts(
        window_seconds: int = Query(
            default=DEFAULT_ACCOUNT_WINDOW_SECONDS,
            ge=MIN_HEALTH_WINDOW_SECONDS,
            le=MAX_HEALTH_WINDOW_SECONDS,
        ),
    ) -> dict[str, Any]:
        result = await _reader().accounts(window_seconds=window_seconds)
        return result.to_json_dict()

    @router.get("/accounts/audit")
    async def read_account_audit(
        limit: int = Query(
            default=DEFAULT_ACCOUNT_AUDIT_LIMIT, ge=1, le=MAX_HISTORY_LIMIT
        ),
    ) -> dict[str, Any]:
        """The overlay's history, its revision, and whether writes are possible.

        Ungated like every other read. It carries ``write_gate`` for the same
        reason the policy read does: a console that rendered live host-admin
        controls and only discovered the gate on click would be offering buttons
        it already knows will 403.
        """
        result = await _reader().account_audit(limit=limit)
        gate = write_gate(config, env=env)
        return {
            **result.to_json_dict(),
            "write_gate": gate.value,
            "editable": gate is WriteGate.ENABLED,
        }

    @router.patch("/accounts/{account_id}/state")
    async def set_account_state(
        account_id: str, body: AccountStateBody, request: Request
    ) -> JSONResponse:
        """Enable, drain, or disable one account against the revision it was read at."""
        actor, refusal = _authorize(request)
        if refusal is not None:
            return refusal
        result = await _writer().set_account_state(
            account_id,
            administrative_state=body.administrative_state,
            expected_revision=body.expected_revision,
            actor=actor,
        )
        return _write_response(result, actor=actor)

    @router.post("/accounts/{account_id}/revoke-leases")
    async def revoke_account_leases(
        account_id: str, body: RevokeLeasesBody, request: Request
    ) -> JSONResponse:
        """End every live lease on one account. Blast radius, so it is audited."""
        actor, refusal = _authorize(request)
        if refusal is not None:
            return refusal
        result = await _writer().revoke_account_leases(
            account_id, expected_revision=body.expected_revision, actor=actor
        )
        return _write_response(result, actor=actor)

    @router.get("/routes/active")
    async def read_active_routes() -> dict[str, Any]:
        result = await _reader().active_routes()
        return result.to_json_dict()

    @router.get("/routes/recent")
    async def read_recent_routes(
        limit: int = Query(default=DEFAULT_RECENT_LIMIT, ge=1, le=MAX_RECENT_LIMIT),
    ) -> dict[str, Any]:
        result = await _reader().recent_routes(limit=limit)
        return result.to_json_dict()

    return router


def _write_response(result: GatewayWriteResult, *, actor: str) -> JSONResponse:
    """Render one mutation outcome, keeping the gateway's own refusal status."""
    if result.state is GatewayWriteState.REFUSED:
        code = _UNNAMED_REFUSAL if result.rejection is None else result.rejection.value
        return _error(
            result.status_code or 409, code, _REFUSAL_DETAIL.get(code, _UNNAMED_DETAIL)
        )
    if not result.applied:
        status_code, code, detail = _WRITE_FAILURE[result.state]
        return _error(status_code, code, detail)
    # `actor` is echoed so the console can show WHOSE name landed on the audit
    # chain — it comes from the authenticated boundary, never from the body.
    return JSONResponse({**(result.data or {}), "actor": actor})


_REFUSAL_DETAIL: dict[str, str] = {
    "stale-revision": (
        "another operator changed the administrative overlay after this view was "
        "loaded; reload the accounts view and decide again"
    ),
    "unknown-account": "the gateway has no account with that id",
    "audit-chain-broken": (
        "the gateway's administrative audit chain does not verify, so it refuses "
        "every mutation until it is repaired"
    ),
}

_UNNAMED_DETAIL = (
    "the gateway refused this mutation with a code this dashboard does not "
    "recognise; check the gateway's own logs"
)


def _error(status_code: int, code: str, detail: str) -> JSONResponse:
    return JSONResponse({"code": code, "detail": detail}, status_code=status_code)
