"""Ephemeral in-flight registry and bounded recent-route read model (ADR-0138).

Observation only. Registering a route changes no routing decision, no mint
semantics, and no proxied byte: the registry is written from the proxy's single
idempotent terminal chokepoint (``GatewayProxy._finalize_attempt``) so an
in-flight row cannot outlive its request on *any* path — success, upstream
error, cancellation, client abort, telemetry failure, or shutdown.

Every published field is non-secret by construction. The virtual token, its
SHA-256 digest, request/response bodies, upstream credentials, and captured body
paths are never carried here; see ``tests/test_gateway_secret_absence.py``.
"""

from __future__ import annotations

import threading
from collections import deque
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import BaseModel, ConfigDict, Field

from hydraflow_gateway.ledger import GatewayLedgerRow
from hydraflow_gateway.models import (
    GatewayIdentity,
    GatewayRequestStatus,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
    legacy_account_id,
)

ROUTE_VIEW_SCHEMA_VERSION = 1
"""Bumped only on a breaking wire change; additive optional fields do not bump it."""

DEFAULT_RECENT_CAPACITY = 200
"""Bounded ring size. Recent evidence is deliberately capped, never a full history."""

MAX_RECENT_LIMIT = 200
"""Ceiling on the ``limit`` a read caller may request."""


@dataclass(frozen=True, slots=True)
class InFlightRoute:
    """One authenticated request the proxy has accepted and not yet finalized."""

    request_id: str
    provider_binding: ProviderBinding
    repo_slug: str
    repo_class: RepoClass
    principal_kind: PrincipalKind
    principal_id: str
    issue_number: int | None
    pr_number: int | None
    path: str | None
    started_at: datetime


@dataclass(frozen=True, slots=True)
class TerminalRoute:
    """One finalized request, retained as bounded recent evidence."""

    request_id: str
    provider_binding: ProviderBinding
    repo_slug: str
    repo_class: RepoClass
    principal_kind: PrincipalKind
    principal_id: str
    issue_number: int | None
    pr_number: int | None
    path: str | None
    model_requested: str | None
    model_served: str | None
    status: GatewayRequestStatus
    status_code: int
    latency_ms: float
    started_at: datetime
    cost_usd: float | None
    cost_unknown: bool


class LeaseView(BaseModel):
    """One unexpired virtual key bound to an account, with no token material.

    ``key_id`` is the random ULID half of the token and is already the ledger's
    non-secret correlation column. The token's secret half is a separate
    high-entropy component of which only a SHA-256 digest is ever retained, so
    ``key_id`` cannot reconstruct or fingerprint a credential.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    key_id: str
    account_id: str
    provider_binding: ProviderBinding
    repo_slug: str
    repo_class: RepoClass
    principal_kind: PrincipalKind
    principal_id: str
    issue_number: int | None = None
    pr_number: int | None = None
    issued_at: datetime
    expires_at: datetime
    age_seconds: float = Field(ge=0)


class InFlightRouteView(BaseModel):
    """One streaming request, sanitized for the operator dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    account_id: str
    provider_binding: ProviderBinding
    repo_slug: str
    repo_class: RepoClass
    principal_kind: PrincipalKind
    principal_id: str
    issue_number: int | None = None
    pr_number: int | None = None
    path: str | None = None
    started_at: datetime
    age_seconds: float = Field(ge=0)


class TerminalRouteView(BaseModel):
    """One finalized request, sanitized for the operator dashboard."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    request_id: str
    account_id: str
    provider_binding: ProviderBinding
    repo_slug: str
    repo_class: RepoClass
    principal_kind: PrincipalKind
    principal_id: str
    issue_number: int | None = None
    pr_number: int | None = None
    path: str | None = None
    model_requested: str | None = None
    model_served: str | None = None
    status: GatewayRequestStatus
    status_code: int
    latency_ms: float = Field(ge=0)
    started_at: datetime
    cost_usd: float | None = None
    cost_unknown: bool


class ActiveRoutesView(BaseModel):
    """Leases and in-flight requests as two independent facts, never one badge."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTE_VIEW_SCHEMA_VERSION
    as_of: datetime
    evidence_since: datetime
    leases: tuple[LeaseView, ...]
    in_flight: tuple[InFlightRouteView, ...]


class RecentRoutesView(BaseModel):
    """Bounded recent terminal routes, explicit about what it cannot show."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTE_VIEW_SCHEMA_VERSION
    as_of: datetime
    evidence_since: datetime
    capacity: int = Field(gt=0)
    truncated: bool
    routes: tuple[TerminalRouteView, ...]


class ActiveRouteRegistry:
    """In-memory route lifecycle owned by one gateway worker process.

    Evidence is process-local and resets on restart; ``evidence_since`` publishes
    exactly that, so the dashboard never claims a complete route history.
    """

    def __init__(
        self,
        *,
        started_at: datetime | None = None,
        recent_capacity: int = DEFAULT_RECENT_CAPACITY,
    ) -> None:
        if recent_capacity <= 0:
            raise ValueError("recent_capacity must be positive")
        self._started_at = started_at or datetime.now(tz=UTC)
        self._recent_capacity = recent_capacity
        self._in_flight: dict[str, InFlightRoute] = {}
        self._recent: deque[TerminalRoute] = deque(maxlen=recent_capacity)
        self._dropped = 0
        self._lock = threading.Lock()

    @property
    def started_at(self) -> datetime:
        """When this process began observing routes."""
        return self._started_at

    @property
    def recent_capacity(self) -> int:
        """Bounded number of terminal routes retained in memory."""
        return self._recent_capacity

    def register(
        self,
        *,
        request_id: str,
        identity: GatewayIdentity,
        path: str | None,
        started_at: datetime,
    ) -> None:
        """Record one accepted request as in-flight."""
        route = InFlightRoute(
            request_id=request_id,
            provider_binding=identity.provider_binding,
            repo_slug=identity.repo_slug,
            repo_class=identity.repo_class,
            principal_kind=identity.principal.kind,
            principal_id=identity.principal.id,
            issue_number=identity.principal.issue_number,
            pr_number=identity.principal.pr_number,
            path=path,
            started_at=started_at,
        )
        with self._lock:
            self._in_flight[request_id] = route

    def release(self, row: GatewayLedgerRow) -> None:
        """Clear one in-flight request and retain it as recent evidence.

        Idempotent: releasing an unknown request id records nothing, so a double
        finalize cannot duplicate a recent row.
        """
        with self._lock:
            if self._in_flight.pop(row.request_id, None) is None:
                return
            if len(self._recent) == self._recent_capacity:
                self._dropped += 1
            self._recent.append(_terminal_route(row))

    def clear(self) -> None:
        """Drop every in-flight row at shutdown; the requests die with the process."""
        with self._lock:
            self._in_flight.clear()

    def in_flight(self) -> tuple[InFlightRoute, ...]:
        """Return a stable snapshot of currently streaming requests."""
        with self._lock:
            routes = tuple(self._in_flight.values())
        return tuple(
            sorted(routes, key=lambda route: (route.started_at, route.request_id))
        )

    def recent(self, limit: int | None = None) -> tuple[TerminalRoute, ...]:
        """Return the most recent terminal routes, newest first."""
        with self._lock:
            routes = tuple(self._recent)
        newest_first = tuple(reversed(routes))
        if limit is None:
            return newest_first
        return newest_first[:limit]

    def truncated(self) -> bool:
        """Whether recent evidence has already been evicted by the ring bound."""
        with self._lock:
            return self._dropped > 0


def _terminal_route(row: GatewayLedgerRow) -> TerminalRoute:
    return TerminalRoute(
        request_id=row.request_id,
        provider_binding=row.upstream_provider,
        repo_slug=row.repo_slug,
        repo_class=row.repo_class,
        principal_kind=row.principal.kind,
        principal_id=row.principal.id,
        issue_number=row.principal.issue_number,
        pr_number=row.principal.pr_number,
        path=row.path,
        model_requested=row.model_requested,
        model_served=row.model_served,
        status=row.status,
        status_code=row.status_code,
        latency_ms=row.latency_ms,
        started_at=row.timestamp,
        cost_usd=row.cost_usd,
        cost_unknown=row.cost_unknown,
    )


def _age_seconds(started_at: datetime, now: datetime) -> float:
    return max(0.0, (now - started_at).total_seconds())


def lease_view(identity: GatewayIdentity, *, now: datetime) -> LeaseView:
    """Project one resolved key identity onto its sanitized lease row."""
    return LeaseView(
        key_id=identity.key_id,
        account_id=legacy_account_id(identity.provider_binding),
        provider_binding=identity.provider_binding,
        repo_slug=identity.repo_slug,
        repo_class=identity.repo_class,
        principal_kind=identity.principal.kind,
        principal_id=identity.principal.id,
        issue_number=identity.principal.issue_number,
        pr_number=identity.principal.pr_number,
        issued_at=identity.issued_at,
        expires_at=identity.expires_at,
        age_seconds=_age_seconds(identity.issued_at, now),
    )


def build_active_routes_view(
    *,
    leases: Iterable[GatewayIdentity],
    in_flight: Sequence[InFlightRoute],
    now: datetime,
    evidence_since: datetime,
) -> ActiveRoutesView:
    """Assemble the read model for leases and streaming requests."""
    return ActiveRoutesView(
        as_of=now,
        evidence_since=evidence_since,
        leases=tuple(lease_view(identity, now=now) for identity in leases),
        in_flight=tuple(
            InFlightRouteView(
                request_id=route.request_id,
                account_id=legacy_account_id(route.provider_binding),
                provider_binding=route.provider_binding,
                repo_slug=route.repo_slug,
                repo_class=route.repo_class,
                principal_kind=route.principal_kind,
                principal_id=route.principal_id,
                issue_number=route.issue_number,
                pr_number=route.pr_number,
                path=route.path,
                started_at=route.started_at,
                age_seconds=_age_seconds(route.started_at, now),
            )
            for route in in_flight
        ),
    )


def build_recent_routes_view(
    *,
    routes: Sequence[TerminalRoute],
    now: datetime,
    evidence_since: datetime,
    capacity: int,
    truncated: bool,
) -> RecentRoutesView:
    """Assemble the bounded read model for finalized routes."""
    return RecentRoutesView(
        as_of=now,
        evidence_since=evidence_since,
        capacity=capacity,
        truncated=truncated,
        routes=tuple(
            TerminalRouteView(
                request_id=route.request_id,
                account_id=legacy_account_id(route.provider_binding),
                provider_binding=route.provider_binding,
                repo_slug=route.repo_slug,
                repo_class=route.repo_class,
                principal_kind=route.principal_kind,
                principal_id=route.principal_id,
                issue_number=route.issue_number,
                pr_number=route.pr_number,
                path=route.path,
                model_requested=route.model_requested,
                model_served=route.model_served,
                status=route.status,
                status_code=route.status_code,
                latency_ms=route.latency_ms,
                started_at=route.started_at,
                cost_usd=route.cost_usd,
                cost_unknown=route.cost_unknown,
            )
            for route in routes
        ),
    )
