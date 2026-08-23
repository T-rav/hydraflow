"""Client for the gateway's v2 account/route control plane (ADR-0138, ADR-0142).

The browser never holds a gateway control credential. HydraFlow's backend owns
the token, calls the gateway with ``trust_env=False``, validates every payload
against the gateway's own models — so schema drift fails closed instead of
reaching the dashboard unchecked — and returns a sanitized envelope that always
says whether the source was actually available.

**The read plane is still read-only by construction.**
:class:`GatewayControlReader` has no mutation method and never will; every
method on it is a GET whose response is validated against a gateway read model.

**The one mutation seam, stated rather than hidden (issue #11540, ADR-0142).**
ADR-0138 §D5 recorded a precondition on any later phase that adds a gateway
write route through this proxy: it must gate on an authenticated operator
identity, and it must be disabled when the dashboard is bound beyond loopback.
:class:`GatewayControlWriter` is that phase's seam, and it is deliberately a
*separate class* so the read plane's guarantee stays verifiable by inspection.
It can call exactly two gateway routes and nothing else:

* ``PATCH /control/v2/accounts/{account_id}/state``
* ``POST  /control/v2/accounts/{account_id}/revoke-leases``

Both are host-admin actions on the gateway's audited administrative overlay;
neither can mint a key, read a credential, or reach the data plane. The writer's
only caller is :mod:`dashboard_routes._gateway_routes`, which refuses to build
one until ``operator_identity.write_gate`` returns ``ENABLED`` (kill switch off,
dashboard bound to loopback, operator credential configured) *and*
``authenticate_operator`` has proved an identity. The ``actor`` recorded on the
gateway's audit chain is that identity's label, passed as a keyword argument —
there is no code path by which a request body can supply one.

Failure discipline is the reader's, unchanged: ``trust_env=False``, a fresh
client per call, no response body ever logged or echoed, and the gateway's own
model validating anything that comes back before it reaches the dashboard.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any
from urllib.parse import quote

import httpx
from pydantic import BaseModel, ValidationError

from hydraflow_gateway.accounts import (
    DEFAULT_HEALTH_WINDOW_SECONDS,
    AccountsView,
    AdministrativeState,
)
from hydraflow_gateway.active_routes import ActiveRoutesView, RecentRoutesView
from hydraflow_gateway.routing_account_admin import (
    DEFAULT_HISTORY_LIMIT,
    AccountAdminAuditView,
    AccountStateRequest,
    AccountStateResponse,
    AdminRejection,
    RevokeLeasesRequest,
    RevokeLeasesResponse,
)
from hydraflow_gateway.routing_policy import (
    canonical_worker_role as _resolver_worker_role,
)

logger = logging.getLogger("hydraflow.gateway.reader")

GATEWAY_CONTROL_TOKEN_ENV = "HYDRAFLOW_GATEWAY_CONTROL_TOKEN"
"""Env-only control credential, deliberately not a config field (see config.py)."""

DEFAULT_READ_TIMEOUT_SECONDS = 5.0
DEFAULT_WRITE_TIMEOUT_SECONDS = 15.0
"""Longer than a read, and deliberately longer than the gateway's own 10s lock
timeout: a client that gave up first would leave an operator unable to say
whether their disable landed, which is the one question this surface exists to
answer."""

DEFAULT_ACCOUNT_WINDOW_SECONDS = DEFAULT_HEALTH_WINDOW_SECONDS
"""Borrowed from the gateway so a bound change cannot 422 every dashboard poll."""

DEFAULT_RECENT_LIMIT = 50
DEFAULT_ACCOUNT_AUDIT_LIMIT = DEFAULT_HISTORY_LIMIT

_ACCOUNTS_PATH = "/control/v2/accounts"
_ACCOUNTS_AUDIT_PATH = "/control/v2/accounts/audit"
_ACTIVE_ROUTES_PATH = "/control/v2/routes/active"
_RECENT_ROUTES_PATH = "/control/v2/routes/recent"

_REFUSAL_PASSTHROUGH_STATUSES = frozenset({404, 409, 503})
"""The gateway statuses that describe the OPERATOR's request rather than this
proxy's own credential or bounds: 404 unknown account, 409 stale revision, 503
broken audit chain. Anything else (401 on the control token, 413 on the body
bound, a 5xx from a crash) is this deployment's problem, and relaying it would
tell the operator their revision was wrong when their revision was fine."""


class GatewaySourceState(StrEnum):
    """Why a gateway read did or did not produce data. Never a silent empty view."""

    AVAILABLE = "available"
    NOT_CONFIGURED = "not-configured"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"


class GatewayWriteState(StrEnum):
    """What one gateway mutation attempt actually did.

    ``REFUSED`` is kept apart from ``UNREACHABLE`` and ``INVALID`` on purpose: a
    refusal means the gateway read the request, checked it, and declined — the
    operator can act on it. The other two mean nobody knows whether anything
    happened, which is a different sentence to put on screen.
    """

    APPLIED = "applied"
    REFUSED = "refused"
    NOT_CONFIGURED = "not-configured"
    UNREACHABLE = "unreachable"
    INVALID = "invalid"


@dataclass(frozen=True, slots=True)
class GatewayReadResult:
    """One sanitized gateway read plus the honest state of its source."""

    state: GatewaySourceState
    data: dict[str, Any] | None = None

    @property
    def available(self) -> bool:
        """Whether the payload is real gateway evidence rather than a placeholder."""
        return self.state is GatewaySourceState.AVAILABLE

    def to_json_dict(self) -> dict[str, Any]:
        """Return the dashboard envelope; ``data`` is null when unavailable."""
        return {
            "available": self.available,
            "source_state": self.state.value,
            "data": self.data,
        }


@dataclass(frozen=True, slots=True)
class GatewayWriteResult:
    """One gateway mutation attempt and the honest disposition of its outcome.

    ``rejection`` is a member of the gateway's own :class:`AdminRejection` enum
    or ``None`` — never the gateway's prose. A refusal code that this build does
    not recognise is reported as an unnamed refusal rather than echoed, because
    echoing an unvalidated string from an authenticated control response is how
    a detail nobody audited reaches an operator's screen.
    """

    state: GatewayWriteState
    data: dict[str, Any] | None = None
    status_code: int | None = None
    rejection: AdminRejection | None = None

    @property
    def applied(self) -> bool:
        """Whether the gateway committed the mutation."""
        return self.state is GatewayWriteState.APPLIED


def canonical_worker_role(principal_id: str) -> str | None:
    """Return the canonical ``WorkerRole`` this principal names, or ``None``.

    Exact match only (ADR-0137 owns the vocabulary). A principal that is a loop
    name, a person, or an unmapped source stays ``None`` rather than being
    guessed into a role the routing resolver would later disagree with.

    The match itself lives in :mod:`hydraflow_gateway.routing_policy`, which is
    where the resolver reads it from. Two copies of "which principals are roles"
    is exactly the drift ADR-0138 §D6 warned about — the observation layer and
    the resolver disagreeing would read as a routing bug.
    """
    role = _resolver_worker_role(principal_id)
    return None if role is None else role.value


def _annotate_roles(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    return [
        {**row, "worker_role": canonical_worker_role(str(row.get("principal_id", "")))}
        for row in rows
    ]


def annotate_active_routes(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the canonical role join to every lease and in-flight row."""
    return {
        **payload,
        "leases": _annotate_roles(list(payload.get("leases", []))),
        "in_flight": _annotate_roles(list(payload.get("in_flight", []))),
    }


def annotate_recent_routes(payload: dict[str, Any]) -> dict[str, Any]:
    """Add the canonical role join to every terminal route row."""
    return {**payload, "routes": _annotate_roles(list(payload.get("routes", [])))}


ClientFactory = Callable[[], httpx.AsyncClient]


class _GatewayControlClient:
    """The transport half both control-plane clients share.

    One place owning ``trust_env=False``, the bearer header, and "a fresh client
    per call" — so the write seam cannot quietly acquire a laxer transport than
    the read plane it sits beside.
    """

    def __init__(
        self,
        *,
        base_url: str,
        control_token: str,
        timeout_seconds: float = DEFAULT_READ_TIMEOUT_SECONDS,
        client_factory: ClientFactory | None = None,
    ) -> None:
        self._base_url = base_url.rstrip("/")
        self._control_token = control_token
        self._timeout_seconds = timeout_seconds
        self._client_factory = client_factory

    @property
    def _configured(self) -> bool:
        """Whether there is a gateway to talk to at all.

        An absent base URL is "not configured", not "unreachable": telling an
        operator to go chase a gateway that was never deployed is the wrong
        instruction, and a relative request URL would otherwise surface as an
        httpx transport error.
        """
        return bool(self._control_token and self._base_url)

    def _auth_headers(self) -> dict[str, str]:
        return {"Authorization": f"Bearer {self._control_token}"}

    def _open(self) -> httpx.AsyncClient:
        """Return a FRESH client per call; the caller closes it via ``async with``.

        ``client_factory`` must therefore construct a client, never hand back a
        shared one — the context manager exit would close it for everybody.
        """
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False)


class GatewayControlReader(_GatewayControlClient):
    """Fetch and validate the gateway's sanitized account and route read models.

    Read-only by construction: every method here is a GET, and the module's one
    mutation seam lives on :class:`GatewayControlWriter` instead.
    """

    async def accounts(
        self, *, window_seconds: int = DEFAULT_ACCOUNT_WINDOW_SECONDS
    ) -> GatewayReadResult:
        """Read sanitized account identities and their independent state facts."""
        return await self._read(
            _ACCOUNTS_PATH,
            params={"window_seconds": window_seconds},
            model=AccountsView,
        )

    async def account_audit(
        self, *, limit: int = DEFAULT_ACCOUNT_AUDIT_LIMIT
    ) -> GatewayReadResult:
        """Read the administrative overlay's hash-linked history and its revision.

        This is also where the console gets the ``revision`` its host-admin
        controls must be composed against: the accounts read model publishes
        per-account facts, not the overlay's counter, so a control that guessed
        one could never lose an optimistic-concurrency race it ought to lose.
        """
        return await self._read(
            _ACCOUNTS_AUDIT_PATH,
            params={"limit": limit},
            model=AccountAdminAuditView,
        )

    async def active_routes(self) -> GatewayReadResult:
        """Read current leases and in-flight requests."""
        result = await self._read(
            _ACTIVE_ROUTES_PATH, params={}, model=ActiveRoutesView
        )
        if result.data is None:
            return result
        return GatewayReadResult(result.state, annotate_active_routes(result.data))

    async def recent_routes(
        self, *, limit: int = DEFAULT_RECENT_LIMIT
    ) -> GatewayReadResult:
        """Read the gateway's bounded recent terminal routes."""
        result = await self._read(
            _RECENT_ROUTES_PATH, params={"limit": limit}, model=RecentRoutesView
        )
        if result.data is None:
            return result
        return GatewayReadResult(result.state, annotate_recent_routes(result.data))

    async def _read(
        self,
        path: str,
        *,
        params: dict[str, Any],
        model: type[BaseModel],
    ) -> GatewayReadResult:
        if not self._configured:
            return GatewayReadResult(GatewaySourceState.NOT_CONFIGURED)
        try:
            async with self._open() as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    headers=self._auth_headers(),
                    params=params,
                )
                response.raise_for_status()
                payload = response.json()
        except (httpx.HTTPError, ValueError):
            # Never retain or log the response: an authenticated control call's
            # failure can flow through long-lived dashboard logs.
            logger.warning("gateway control read failed for %s", path)
            return GatewayReadResult(GatewaySourceState.UNREACHABLE)
        try:
            validated = model.model_validate(payload)
        except ValidationError:
            logger.warning(
                "gateway control read returned an unknown shape for %s", path
            )
            return GatewayReadResult(GatewaySourceState.INVALID)
        return GatewayReadResult(
            GatewaySourceState.AVAILABLE, validated.model_dump(mode="json")
        )


class GatewayControlWriter(_GatewayControlClient):
    """The gateway's two host-admin mutations, and nothing else (ADR-0142).

    Every method takes ``actor`` as a keyword argument rather than accepting a
    request body: the caller is ``dashboard_routes._gateway_routes``, which has
    already proved an operator identity, and there is no overload here that
    would let a browser-supplied string reach the gateway's audit chain.
    """

    def __init__(
        self,
        *,
        base_url: str,
        control_token: str,
        timeout_seconds: float = DEFAULT_WRITE_TIMEOUT_SECONDS,
        client_factory: ClientFactory | None = None,
    ) -> None:
        super().__init__(
            base_url=base_url,
            control_token=control_token,
            timeout_seconds=timeout_seconds,
            client_factory=client_factory,
        )

    async def set_account_state(
        self,
        account_id: str,
        *,
        administrative_state: AdministrativeState,
        expected_revision: int,
        actor: str,
    ) -> GatewayWriteResult:
        """Enable, drain, or disable one account against a declared revision."""
        return await self._write(
            "PATCH",
            f"{_ACCOUNTS_PATH}/{quote(account_id, safe='')}/state",
            body=AccountStateRequest(
                administrative_state=administrative_state,
                expected_revision=expected_revision,
                actor=actor,
            ),
            model=AccountStateResponse,
        )

    async def revoke_account_leases(
        self, account_id: str, *, expected_revision: int, actor: str
    ) -> GatewayWriteResult:
        """End every live lease on one account. A blast-radius action, audited."""
        return await self._write(
            "POST",
            f"{_ACCOUNTS_PATH}/{quote(account_id, safe='')}/revoke-leases",
            body=RevokeLeasesRequest(expected_revision=expected_revision, actor=actor),
            model=RevokeLeasesResponse,
        )

    async def _write(
        self,
        method: str,
        path: str,
        *,
        body: BaseModel,
        model: type[BaseModel],
    ) -> GatewayWriteResult:
        if not self._configured:
            return GatewayWriteResult(GatewayWriteState.NOT_CONFIGURED)
        try:
            async with self._open() as client:
                response = await client.request(
                    method,
                    f"{self._base_url}{path}",
                    headers={
                        **self._auth_headers(),
                        "Content-Type": "application/json",
                    },
                    # The gateway's OWN request model serialises the body, so a
                    # field it does not accept cannot be invented here either.
                    content=body.model_dump_json(),
                )
                payload = _payload_or_none(response)
        except httpx.HTTPError:
            # A transport failure on a write is the ambiguous case: the mutation
            # may or may not have committed. Say "unreachable" and let the
            # console tell the operator to re-read, never "it failed".
            logger.warning("gateway control write failed for %s", path)
            return GatewayWriteResult(GatewayWriteState.UNREACHABLE)
        if response.status_code >= 400:
            return _refusal(response.status_code, payload, path)
        try:
            validated = model.model_validate(payload)
        except ValidationError:
            logger.warning(
                "gateway control write returned an unknown shape for %s", path
            )
            return GatewayWriteResult(GatewayWriteState.INVALID)
        return GatewayWriteResult(
            GatewayWriteState.APPLIED, validated.model_dump(mode="json")
        )


def _payload_or_none(response: httpx.Response) -> Any:
    """Decode a control response, or ``None`` when it carried no JSON."""
    try:
        return response.json()
    except ValueError:
        return None


def _refusal(status_code: int, payload: Any, path: str) -> GatewayWriteResult:
    """Map one gateway refusal onto a disposition the operator can act on."""
    if status_code not in _REFUSAL_PASSTHROUGH_STATUSES:
        # Never relayed: a 401 here means THIS proxy's control token is wrong,
        # and answering the operator with it would blame their request.
        logger.warning(
            "gateway control write was rejected with status %s for %s",
            status_code,
            path,
        )
        return GatewayWriteResult(GatewayWriteState.UNREACHABLE)
    return GatewayWriteResult(
        GatewayWriteState.REFUSED,
        status_code=status_code,
        rejection=_known_rejection(payload),
    )


def _known_rejection(payload: Any) -> AdminRejection | None:
    """Return the gateway's refusal code only if it is one this build knows."""
    detail = payload.get("detail") if isinstance(payload, dict) else None
    try:
        return AdminRejection(detail)
    except ValueError:
        return None


def reader_from_config(
    config: Any, *, client_factory: ClientFactory | None = None
) -> GatewayControlReader:
    """Build a reader from the dashboard's config and the env-only control token."""
    return GatewayControlReader(
        base_url=str(getattr(config, "gateway_base_url", "") or ""),
        control_token=_control_token(),
        client_factory=client_factory,
    )


def writer_from_config(
    config: Any, *, client_factory: ClientFactory | None = None
) -> GatewayControlWriter:
    """Build the host-admin writer. Callers must have passed the operator gate."""
    return GatewayControlWriter(
        base_url=str(getattr(config, "gateway_base_url", "") or ""),
        control_token=_control_token(),
        client_factory=client_factory,
    )


def _control_token() -> str:
    """The one env-only control credential both clients present."""
    return os.environ.get(GATEWAY_CONTROL_TOKEN_ENV, "").strip()
