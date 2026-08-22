"""Read-only client for the gateway's v2 account/route control plane (ADR-0138).

The browser never holds a gateway control credential. HydraFlow's backend owns
the token, calls the gateway with ``trust_env=False``, validates every payload
against the gateway's own read models — so schema drift fails closed instead of
reaching the dashboard unchecked — and returns a sanitized envelope that always
says whether the source was actually available.

Read-only by construction: this module has no mutation method, and the gateway
exposes no v2 write endpoint for it to call.
"""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from enum import StrEnum
from typing import Any

import httpx
from pydantic import BaseModel, ValidationError

from driver_contracts import WorkerRole
from hydraflow_gateway.accounts import DEFAULT_HEALTH_WINDOW_SECONDS, AccountsView
from hydraflow_gateway.active_routes import ActiveRoutesView, RecentRoutesView

logger = logging.getLogger("hydraflow.gateway.reader")

GATEWAY_CONTROL_TOKEN_ENV = "HYDRAFLOW_GATEWAY_CONTROL_TOKEN"
"""Env-only control credential, deliberately not a config field (see config.py)."""

DEFAULT_READ_TIMEOUT_SECONDS = 5.0
DEFAULT_ACCOUNT_WINDOW_SECONDS = DEFAULT_HEALTH_WINDOW_SECONDS
"""Borrowed from the gateway so a bound change cannot 422 every dashboard poll."""

DEFAULT_RECENT_LIMIT = 50

_ACCOUNTS_PATH = "/control/v2/accounts"
_ACTIVE_ROUTES_PATH = "/control/v2/routes/active"
_RECENT_ROUTES_PATH = "/control/v2/routes/recent"

_ROLE_VALUES = frozenset(role.value for role in WorkerRole)


class GatewaySourceState(StrEnum):
    """Why a gateway read did or did not produce data. Never a silent empty view."""

    AVAILABLE = "available"
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


def canonical_worker_role(principal_id: str) -> str | None:
    """Return the canonical ``WorkerRole`` this principal names, or ``None``.

    Exact match only (ADR-0137 owns the vocabulary). A principal that is a loop
    name, a person, or an unmapped source stays ``None`` rather than being
    guessed into a role the routing resolver would later disagree with.
    """
    candidate = principal_id.strip().lower()
    return candidate if candidate in _ROLE_VALUES else None


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


class GatewayControlReader:
    """Fetch and validate the gateway's sanitized account and route read models."""

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

    async def accounts(
        self, *, window_seconds: int = DEFAULT_ACCOUNT_WINDOW_SECONDS
    ) -> GatewayReadResult:
        """Read sanitized account identities and their independent state facts."""
        return await self._read(
            _ACCOUNTS_PATH,
            params={"window_seconds": window_seconds},
            model=AccountsView,
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
        # An absent base URL is "not configured", not "unreachable": telling an
        # operator to go chase a gateway that was never deployed is the wrong
        # instruction, and a relative request URL would otherwise surface as an
        # httpx transport error.
        if not self._control_token or not self._base_url:
            return GatewayReadResult(GatewaySourceState.NOT_CONFIGURED)
        try:
            async with self._open() as client:
                response = await client.get(
                    f"{self._base_url}{path}",
                    headers={"Authorization": f"Bearer {self._control_token}"},
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

    def _open(self) -> httpx.AsyncClient:
        """Return a FRESH client per read; the caller closes it via ``async with``.

        ``client_factory`` must therefore construct a client, never hand back a
        shared one — the context manager exit would close it for everybody.
        """
        if self._client_factory is not None:
            return self._client_factory()
        return httpx.AsyncClient(timeout=self._timeout_seconds, trust_env=False)


def reader_from_config(
    config: Any, *, client_factory: ClientFactory | None = None
) -> GatewayControlReader:
    """Build a reader from the dashboard's config and the env-only control token."""
    return GatewayControlReader(
        base_url=str(getattr(config, "gateway_base_url", "") or ""),
        control_token=os.environ.get(GATEWAY_CONTROL_TOKEN_ENV, "").strip(),
        client_factory=client_factory,
    )
