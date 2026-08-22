"""``hydraflow_gateway.accounts`` — identity compilation and state derivation.

ADR-0138. Named for the module it covers (the P10.2 unit-ring rule), not for the
``test_gateway_*`` grouping the rest of the gateway suite uses.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import SecretStr

from hydraflow_gateway.accounts import (
    ACCOUNT_DISPLAY_NAMES,
    CREDENTIAL_ENV_NAMES,
    AccountHealth,
    AccountHealthReason,
    AccountsView,
    AccountView,
    AdministrativeState,
    build_accounts_view,
)
from hydraflow_gateway.active_routes import InFlightRoute, TerminalRoute
from hydraflow_gateway.models import (
    LEGACY_ACCOUNT_IDS,
    GatewayIdentity,
    GatewayRequestStatus,
    Principal,
    PrincipalKind,
    ProviderBinding,
    RepoClass,
)
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_CONTROL_TOKEN = "test-control-token-0123456789abcdef"
_NOW = datetime(2026, 8, 22, 12, 0, 0, tzinfo=UTC)
_EVIDENCE_SINCE = _NOW - timedelta(hours=1)


def _settings(*bindings: ProviderBinding) -> GatewaySettings:
    styles = {
        ProviderBinding.ANTHROPIC: UpstreamAuthStyle.X_API_KEY,
        ProviderBinding.ZAI_HARNESS: UpstreamAuthStyle.BEARER,
    }
    urls = {
        ProviderBinding.ANTHROPIC: "https://api.anthropic.test/v1",
        ProviderBinding.ZAI_HARNESS: "https://api.z.ai.test/api/anthropic",
    }
    return GatewaySettings(
        control_token=SecretStr(_CONTROL_TOKEN),
        upstreams={
            binding: UpstreamSettings(
                base_url=urls[binding],
                api_key=SecretStr("provider-secret-value"),
                auth_style=styles[binding],
            )
            for binding in bindings
        },
    )


def _lease(binding: ProviderBinding, *, key_id: str = "lease-1") -> GatewayIdentity:
    return GatewayIdentity(
        key_id=key_id,
        principal=Principal(kind=PrincipalKind.SPAWN, id="implementer", spawn_id="s1"),
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        provider_binding=binding,
        body_capture_policy="metadata-only",
        issued_at=_NOW - timedelta(seconds=30),
        expires_at=_NOW + timedelta(seconds=270),
    )


def _in_flight(binding: ProviderBinding, *, request_id: str = "req-1") -> InFlightRoute:
    return InFlightRoute(
        request_id=request_id,
        provider_binding=binding,
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        principal_kind=PrincipalKind.SPAWN,
        principal_id="implementer",
        issue_number=11534,
        pr_number=None,
        path="/v1/messages",
        started_at=_NOW - timedelta(seconds=5),
    )


def _recent(
    binding: ProviderBinding,
    *,
    status: GatewayRequestStatus = GatewayRequestStatus.COMPLETED,
    age_seconds: int = 10,
    request_id: str = "req-old",
) -> TerminalRoute:
    return TerminalRoute(
        request_id=request_id,
        provider_binding=binding,
        repo_slug="acme/hydraflow",
        repo_class=RepoClass.HYDRAFLOW,
        principal_kind=PrincipalKind.SPAWN,
        principal_id="implementer",
        issue_number=11534,
        pr_number=None,
        path="/v1/messages",
        model_requested="glm-5.3",
        model_served="glm-5.3",
        status=status,
        status_code=200 if status is GatewayRequestStatus.COMPLETED else 502,
        latency_ms=42.0,
        started_at=_NOW - timedelta(seconds=age_seconds),
        cost_usd=0.01,
        cost_unknown=False,
    )


def _view(
    settings: GatewaySettings,
    *,
    leases: tuple[GatewayIdentity, ...] = (),
    in_flight: tuple[InFlightRoute, ...] = (),
    recent: tuple[TerminalRoute, ...] = (),
    window_seconds: int = 900,
) -> AccountsView:
    return build_accounts_view(
        settings=settings,
        leases=leases,
        in_flight=in_flight,
        recent=recent,
        now=_NOW,
        window_seconds=window_seconds,
        evidence_since=_EVIDENCE_SINCE,
    )


def _account(view: AccountsView, account_id: str) -> AccountView:
    return next(a for a in view.accounts if a.account_id == account_id)


def test_legacy_anthropic_pair_compiles_to_a_stable_account_id() -> None:
    """The env-pair upstream becomes the deterministic ``legacy-anthropic`` id."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert _account(view, "legacy-anthropic").provider_binding is (
        ProviderBinding.ANTHROPIC
    )


def test_legacy_zai_pair_compiles_to_a_stable_account_id() -> None:
    """The z.ai env pair becomes the deterministic ``legacy-zai-harness`` id."""
    view = _view(_settings(ProviderBinding.ZAI_HARNESS))

    assert _account(view, "legacy-zai-harness").configured is True


def test_unconfigured_binding_is_listed_as_not_configured() -> None:
    """A provider with no credential is still an account, marked unconfigured."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert _account(view, "legacy-zai-harness").configured is False


def test_base_origin_drops_the_upstream_path() -> None:
    """Only the validated origin is published, never the full upstream URL."""
    view = _view(_settings(ProviderBinding.ZAI_HARNESS))

    assert _account(view, "legacy-zai-harness").base_origin == "https://api.z.ai.test"


def test_unconfigured_account_publishes_no_base_origin() -> None:
    """An account without a credential has nothing to say about its upstream."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert _account(view, "legacy-zai-harness").base_origin is None


def test_account_names_the_environment_variable_that_configures_it() -> None:
    """Operators need the variable name to fix an unconfigured account."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert (
        _account(view, "legacy-anthropic").credential_env == "GATEWAY_ANTHROPIC_API_KEY"
    )


def test_administrative_state_is_enabled_without_an_overlay() -> None:
    """P0 ships no administrative overlay, so every account reads ``enabled``."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert (
        _account(view, "legacy-anthropic").administrative_state
        is AdministrativeState.ENABLED
    )


def test_lease_count_groups_keys_by_their_bound_account() -> None:
    """Leases are counted per account, not globally."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC, ProviderBinding.ZAI_HARNESS),
        leases=(_lease(ProviderBinding.ANTHROPIC),),
    )

    assert _account(view, "legacy-anthropic").lease_count == 1


def test_leased_is_false_for_an_account_with_no_key() -> None:
    """``leased`` is an independent fact, not implied by being configured."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC, ProviderBinding.ZAI_HARNESS),
        leases=(_lease(ProviderBinding.ANTHROPIC),),
    )

    assert _account(view, "legacy-zai-harness").leased is False


def test_in_flight_count_reflects_streaming_requests() -> None:
    """``in_flight`` counts authenticated requests, not leases."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        leases=(_lease(ProviderBinding.ANTHROPIC),),
        in_flight=(_in_flight(ProviderBinding.ANTHROPIC),),
    )

    assert _account(view, "legacy-anthropic").in_flight_count == 1


def test_leased_account_without_a_request_is_not_in_flight() -> None:
    """ "2 leases, no request yet" must be distinguishable from active traffic."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        leases=(_lease(ProviderBinding.ANTHROPIC),),
    )

    assert _account(view, "legacy-anthropic").in_flight is False


def test_observed_is_false_without_terminal_evidence() -> None:
    """No terminal row in the window means the account was not observed."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert _account(view, "legacy-anthropic").observed is False


def test_observed_records_the_last_terminal_row_timestamp() -> None:
    """Observation carries its own ``as_of`` evidence, not a bare boolean."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        recent=(_recent(ProviderBinding.ANTHROPIC, age_seconds=10),),
    )

    assert _account(view, "legacy-anthropic").last_observed_at == _NOW - timedelta(
        seconds=10
    )


def test_terminal_rows_outside_the_window_are_not_observed() -> None:
    """An old row must not make a quiet account look active."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        recent=(_recent(ProviderBinding.ANTHROPIC, age_seconds=5_000),),
        window_seconds=900,
    )

    assert _account(view, "legacy-anthropic").observed is False


def test_unconfigured_account_health_is_unverified_for_a_missing_credential() -> None:
    """A missing secret is a named reason, never a degraded-looking guess."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))
    account = _account(view, "legacy-zai-harness")

    assert account.health_reason is AccountHealthReason.CREDENTIAL_MISSING


def test_configured_account_without_evidence_is_unverified() -> None:
    """ "Key configured" must never render as healthy."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert _account(view, "legacy-anthropic").health is AccountHealth.UNVERIFIED


def test_successful_traffic_makes_an_account_healthy() -> None:
    """Passive success evidence inside the window is the only healthy signal."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        recent=(_recent(ProviderBinding.ANTHROPIC),),
    )

    assert _account(view, "legacy-anthropic").health is AccountHealth.HEALTHY


def test_sustained_upstream_errors_degrade_an_account() -> None:
    """Enough qualifying failures in the window flip the lane to degraded."""
    errors = tuple(
        _recent(
            ProviderBinding.ANTHROPIC,
            status=GatewayRequestStatus.UPSTREAM_ERROR,
            request_id=f"err-{index}",
        )
        for index in range(3)
    )
    view = _view(_settings(ProviderBinding.ANTHROPIC), recent=errors)

    assert _account(view, "legacy-anthropic").health is AccountHealth.DEGRADED


def test_a_single_error_does_not_degrade_an_account() -> None:
    """One failure is noise; the threshold keeps the badge honest."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        recent=(
            _recent(
                ProviderBinding.ANTHROPIC,
                status=GatewayRequestStatus.UPSTREAM_ERROR,
                request_id="err-0",
            ),
        ),
    )

    assert _account(view, "legacy-anthropic").health is AccountHealth.HEALTHY


def test_client_aborts_are_not_health_evidence_about_the_account() -> None:
    """A client hang-up says nothing upstream, so it proves neither health nor fault."""
    aborts = tuple(
        _recent(
            ProviderBinding.ANTHROPIC,
            status=GatewayRequestStatus.CLIENT_ABORTED,
            request_id=f"abort-{index}",
        )
        for index in range(4)
    )
    view = _view(_settings(ProviderBinding.ANTHROPIC), recent=aborts)

    assert _account(view, "legacy-anthropic").health is AccountHealth.UNVERIFIED


def test_client_aborts_are_still_counted_as_observed_traffic() -> None:
    """The account was reached, so ``observed`` is true even with no health verdict."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        recent=(
            _recent(
                ProviderBinding.ANTHROPIC,
                status=GatewayRequestStatus.CLIENT_ABORTED,
                request_id="abort-0",
            ),
        ),
    )

    assert _account(view, "legacy-anthropic").observed is True


def test_summary_counts_configured_accounts_only() -> None:
    """The overview counts configured/leased/in-flight, never "eligible"."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert view.summary.configured == 1


def test_summary_counts_in_flight_accounts() -> None:
    """Overview in-flight is an account count, not a request count."""
    view = _view(
        _settings(ProviderBinding.ANTHROPIC),
        in_flight=(
            _in_flight(ProviderBinding.ANTHROPIC, request_id="a"),
            _in_flight(ProviderBinding.ANTHROPIC, request_id="b"),
        ),
    )

    assert view.summary.in_flight == 1


def test_view_pins_the_evidence_window_it_was_computed_from() -> None:
    """Every time-derived fact carries its window so the UI cannot overclaim."""
    view = _view(_settings(ProviderBinding.ANTHROPIC), window_seconds=600)

    assert view.window_seconds == 600


def test_view_pins_the_moment_observation_began() -> None:
    """In-memory evidence resets on restart; ``evidence_since`` says so."""
    view = _view(_settings(ProviderBinding.ANTHROPIC))

    assert view.evidence_since == _EVIDENCE_SINCE


def test_the_aborted_count_makes_the_health_verdict_reproducible() -> None:
    """Publishing aborts lets a reader recompute the denominator health used."""
    rows = (
        _recent(
            ProviderBinding.ANTHROPIC,
            status=GatewayRequestStatus.CLIENT_ABORTED,
            request_id="abort-0",
        ),
        _recent(ProviderBinding.ANTHROPIC, request_id="ok-0"),
    )
    account = _account(
        _view(_settings(ProviderBinding.ANTHROPIC), recent=rows), "legacy-anthropic"
    )

    assert account.observed_request_count - account.observed_aborted_count == 1


def test_truncated_evidence_is_declared_on_the_accounts_view() -> None:
    """Health computed from an evicted subsample must not read as complete."""
    view = build_accounts_view(
        settings=_settings(ProviderBinding.ANTHROPIC),
        leases=(),
        in_flight=(),
        recent=(),
        now=_NOW,
        evidence_since=_EVIDENCE_SINCE,
        evidence_truncated=True,
    )

    assert view.evidence_truncated is True


@pytest.mark.parametrize(
    "table", [LEGACY_ACCOUNT_IDS, ACCOUNT_DISPLAY_NAMES, CREDENTIAL_ENV_NAMES]
)
def test_account_metadata_covers_every_provider_binding(
    table: Mapping[ProviderBinding, str],
) -> None:
    """A new binding must not KeyError every v2 read endpoint at once."""
    assert set(table) == set(ProviderBinding)


def test_accounts_are_ordered_deterministically_by_id() -> None:
    """A stable order keeps the UI and its fixtures reproducible."""
    view = _view(_settings(ProviderBinding.ANTHROPIC, ProviderBinding.ZAI_HARNESS))

    assert [account.account_id for account in view.accounts] == [
        "legacy-anthropic",
        "legacy-zai-harness",
    ]
