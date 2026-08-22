"""Sanitized account identities compiled from server-owned upstreams (ADR-0138).

Pure projection: nothing here reads a credential, mints a key, or influences a
routing decision. It compiles the v1 ``GATEWAY_<PROVIDER>_{BASE_URL,API_KEY}``
environment pairs into stable account identities and derives the independent
observation facts an operator needs — ``configured``, administrative state,
``leased``, ``in_flight``, ``observed``, and passive health — as *separate*
fields, so "key configured" can never render as "healthy" and "healthy" can
never render as "currently routing".

``eligible`` is deliberately absent: eligibility exists only inside a route
explanation, which is the policy resolver's job (a later phase), not an
account-global fact.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping, Sequence
from datetime import datetime, timedelta
from enum import StrEnum
from types import MappingProxyType
from urllib.parse import urlsplit

from pydantic import BaseModel, ConfigDict, Field

from hydraflow_gateway.active_routes import (
    ROUTE_VIEW_SCHEMA_VERSION,
    InFlightRoute,
    TerminalRoute,
)
from hydraflow_gateway.models import (
    GatewayIdentity,
    GatewayRequestStatus,
    ProviderBinding,
    legacy_account_id,
)
from hydraflow_gateway.settings import GatewaySettings

DEFAULT_HEALTH_WINDOW_SECONDS = 900
"""Default passive-evidence window. Every time-derived fact publishes its window."""

MIN_HEALTH_WINDOW_SECONDS = 60
MAX_HEALTH_WINDOW_SECONDS = 86_400

DEGRADED_MIN_ERRORS = 3
"""Below this, upstream failures are noise rather than a lane verdict."""

DEGRADED_ERROR_RATIO = 0.5
"""Share of qualifying terminal rows that must have failed to call a lane degraded."""

ACCOUNT_DISPLAY_NAMES: Mapping[ProviderBinding, str] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: "Anthropic (legacy upstream)",
        ProviderBinding.ZAI_HARNESS: "z.ai harness (legacy upstream)",
    }
)

CREDENTIAL_ENV_NAMES: Mapping[ProviderBinding, str] = MappingProxyType(
    {
        ProviderBinding.ANTHROPIC: "GATEWAY_ANTHROPIC_API_KEY",
        ProviderBinding.ZAI_HARNESS: "GATEWAY_ZAI_HARNESS_API_KEY",
    }
)
"""The *name* of the variable that configures an account — never its value."""


class AdministrativeState(StrEnum):
    """Live overlay permitting new leases, only existing leases, or no traffic."""

    ENABLED = "enabled"
    DRAINING = "draining"
    DISABLED = "disabled"


class AccountHealth(StrEnum):
    """Passive evidence verdict for one account. An unknown result is never healthy."""

    UNVERIFIED = "unverified"
    HEALTHY = "healthy"
    DEGRADED = "degraded"


class AccountHealthReason(StrEnum):
    """Why an account carries its current health, as a code rather than prose."""

    CREDENTIAL_MISSING = "credential-missing"
    NO_EVIDENCE = "no-evidence"
    UPSTREAM_ERRORS = "upstream-errors"


class AccountView(BaseModel):
    """One account's identity plus its independent, sanitized observation facts."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    account_id: str
    display_name: str
    provider_binding: ProviderBinding
    base_origin: str | None = None
    auth_style: str | None = None
    credential_env: str | None = None
    configured: bool
    administrative_state: AdministrativeState
    leased: bool
    lease_count: int = Field(ge=0)
    in_flight: bool
    in_flight_count: int = Field(ge=0)
    observed: bool
    observed_request_count: int = Field(ge=0)
    # Client aborts are observed traffic but say nothing upstream, so they are
    # excluded from the health verdict. Publishing the count keeps the verdict
    # reproducible from the wire: qualifying = requests - aborted.
    observed_aborted_count: int = Field(default=0, ge=0)
    observed_error_count: int = Field(ge=0)
    last_observed_at: datetime | None = None
    health: AccountHealth
    health_reason: AccountHealthReason | None = None


class AccountSummary(BaseModel):
    """Overview counters. Counts configured/enabled/leased/in-flight, never eligible."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    configured: int = Field(ge=0)
    enabled: int = Field(ge=0)
    leased: int = Field(ge=0)
    in_flight: int = Field(ge=0)


class AccountsView(BaseModel):
    """The read model behind ``GET /control/v2/accounts``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    schema_version: int = ROUTE_VIEW_SCHEMA_VERSION
    as_of: datetime
    window_seconds: int = Field(gt=0)
    evidence_since: datetime
    # Health is derived from the gateway's bounded terminal-route ring. Once the
    # ring has evicted, the window is a subsample and the view says so rather
    # than presenting "healthy over 900s" computed from part of it.
    evidence_truncated: bool = False
    summary: AccountSummary
    accounts: tuple[AccountView, ...]


def base_origin(base_url: str) -> str:
    """Return the validated scheme+authority of an upstream, dropping its path."""
    parsed = urlsplit(base_url)
    return f"{parsed.scheme}://{parsed.netloc}"


def derive_health(
    *,
    configured: bool,
    request_count: int,
    error_count: int,
) -> tuple[AccountHealth, AccountHealthReason | None]:
    """Return the passive verdict for one account from bounded terminal evidence."""
    if not configured:
        return AccountHealth.UNVERIFIED, AccountHealthReason.CREDENTIAL_MISSING
    if request_count == 0:
        return AccountHealth.UNVERIFIED, AccountHealthReason.NO_EVIDENCE
    crossed_floor = error_count >= DEGRADED_MIN_ERRORS
    crossed_ratio = error_count / request_count >= DEGRADED_ERROR_RATIO
    if crossed_floor and crossed_ratio:
        return AccountHealth.DEGRADED, AccountHealthReason.UPSTREAM_ERRORS
    return AccountHealth.HEALTHY, None


def build_accounts_view(
    *,
    settings: GatewaySettings,
    leases: Iterable[GatewayIdentity],
    in_flight: Sequence[InFlightRoute],
    recent: Sequence[TerminalRoute],
    now: datetime,
    window_seconds: int = DEFAULT_HEALTH_WINDOW_SECONDS,
    evidence_since: datetime,
    evidence_truncated: bool = False,
) -> AccountsView:
    """Compile every provider binding into one sanitized account read model."""
    cutoff = now - timedelta(seconds=window_seconds)
    lease_counts: dict[ProviderBinding, int] = {}
    for identity in leases:
        lease_counts[identity.provider_binding] = (
            lease_counts.get(identity.provider_binding, 0) + 1
        )
    in_flight_counts: dict[ProviderBinding, int] = {}
    for route in in_flight:
        in_flight_counts[route.provider_binding] = (
            in_flight_counts.get(route.provider_binding, 0) + 1
        )

    accounts: list[AccountView] = []
    for binding in ProviderBinding:
        upstream = settings.upstreams.get(binding)
        observed_rows = [
            row
            for row in recent
            if row.provider_binding is binding and row.started_at >= cutoff
        ]
        # A client hang-up says nothing about the account, so it is neither
        # qualifying evidence nor a failure.
        qualifying = [
            row
            for row in observed_rows
            if row.status is not GatewayRequestStatus.CLIENT_ABORTED
        ]
        error_count = sum(
            1 for row in qualifying if row.status is GatewayRequestStatus.UPSTREAM_ERROR
        )
        health, reason = derive_health(
            configured=upstream is not None,
            request_count=len(qualifying),
            error_count=error_count,
        )
        lease_count = lease_counts.get(binding, 0)
        in_flight_count = in_flight_counts.get(binding, 0)
        accounts.append(
            AccountView(
                account_id=legacy_account_id(binding),
                display_name=ACCOUNT_DISPLAY_NAMES[binding],
                provider_binding=binding,
                base_origin=None
                if upstream is None
                else base_origin(upstream.base_url),
                auth_style=None if upstream is None else upstream.auth_style.value,
                credential_env=CREDENTIAL_ENV_NAMES[binding],
                configured=upstream is not None,
                administrative_state=AdministrativeState.ENABLED,
                leased=lease_count > 0,
                lease_count=lease_count,
                in_flight=in_flight_count > 0,
                in_flight_count=in_flight_count,
                observed=bool(observed_rows),
                observed_request_count=len(observed_rows),
                observed_aborted_count=len(observed_rows) - len(qualifying),
                observed_error_count=error_count,
                last_observed_at=(
                    max(row.started_at for row in observed_rows)
                    if observed_rows
                    else None
                ),
                health=health,
                health_reason=reason,
            )
        )
    accounts.sort(key=lambda account: account.account_id)
    return AccountsView(
        as_of=now,
        window_seconds=window_seconds,
        evidence_since=evidence_since,
        evidence_truncated=evidence_truncated,
        summary=AccountSummary(
            configured=sum(1 for account in accounts if account.configured),
            enabled=sum(
                1
                for account in accounts
                if account.configured
                and account.administrative_state is AdministrativeState.ENABLED
            ),
            leased=sum(1 for account in accounts if account.leased),
            in_flight=sum(1 for account in accounts if account.in_flight),
        ),
        accounts=tuple(accounts),
    )
