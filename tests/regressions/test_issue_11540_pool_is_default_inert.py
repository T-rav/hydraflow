"""#11540: a deployment that asked for no pool must not have been given one.

ADR-0142's first claim is that pools and bounded fallback are *additive*: with no
accounts file, a gateway has exactly ADR-0138's two compiled legacy accounts,
every candidate list has one entry, no hop has anywhere to go, and no account has
a ceiling it never declared. That is easy to believe and easy to break — a
default capacity, a reordered registry, or a fallback that starts from position 0
on an unknown citation would each silently move traffic on a deployment that
changed nothing.

Each test below is one way that could go wrong, and the pair at the end asserts
the machinery *does* engage once a file exists, so none of it is vacuous.
"""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import SecretStr

from hydraflow_gateway.keys import VirtualKeyStore
from hydraflow_gateway.models import ProviderBinding, legacy_account_id
from hydraflow_gateway.route_mint import MintV2Request, RouteMintStore
from hydraflow_gateway.routing_accounts import load_account_pool
from hydraflow_gateway.routing_policy import DecisionOutcome
from hydraflow_gateway.settings import (
    GatewaySettings,
    UpstreamAuthStyle,
    UpstreamSettings,
)

_ZAI = legacy_account_id(ProviderBinding.ZAI_HARNESS)
_SECONDARY = "zai-secondary"

_DOCUMENT = f"""
schema_version: 1
accounts:
  - id: {_SECONDARY}
    provider_binding: zai-harness
    base_url: https://api2.z.ai
    auth_style: bearer
    credential_env: GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY
"""


def _settings(**overrides: object) -> GatewaySettings:
    payload: dict[str, object] = {
        "control_token": SecretStr("inert-regression-control-token-0123456789"),
        "upstreams": {
            binding: UpstreamSettings(
                base_url=f"https://{binding.value}.test",
                api_key=SecretStr("inert-regression-upstream-key"),
                auth_style=UpstreamAuthStyle.BEARER,
            )
            for binding in ProviderBinding
        },
    }
    payload.update(overrides)
    return GatewaySettings(**payload)  # type: ignore[arg-type]


def _request(**overrides: object) -> MintV2Request:
    payload: dict[str, object] = {
        "mint_attempt_id": "att-1",
        "dispatch_id": "disp-1",
        "principal_kind": "spawn",
        "principal_id": "implementer",
        "spawn_id": "spawn-1",
        "repo": "acme/hydraflow",
        "repo_slug": "acme-hydraflow",
        "repo_class": "hydraflow",
        "request_face": "agentic",
        "requirement_kind": "capability",
        "requirement_value": "balanced",
        "effective_model": "glm-5.3",
        "route_decision_id": "dec_inert",
        "ttl_seconds": 600,
    }
    payload.update(overrides)
    return MintV2Request.model_validate(payload)


def _store(settings: GatewaySettings, environ: dict[str, str] | None = None):  # noqa: ANN202
    return RouteMintStore(
        key_store=VirtualKeyStore(max_ttl_seconds=86_400),
        pool=load_account_pool(settings, environ or {}),
        wall_clock=lambda: 1_700_000_000.0,
    )


# -- with no accounts file, nothing about a pool exists ----------------------


def test_a_deployment_with_no_accounts_file_has_only_the_legacy_accounts() -> None:
    pool = load_account_pool(_settings(), {})

    assert pool.registry.account_ids == (
        legacy_account_id(ProviderBinding.ANTHROPIC),
        _ZAI,
    )


def test_a_lane_with_no_pool_offers_exactly_one_candidate() -> None:
    assert load_account_pool(_settings(), {}).candidates_for_model("glm-5.3") == (_ZAI,)


@pytest.mark.parametrize(
    "ceiling",
    [
        pytest.param("lease_capacity", id="leases"),
        pytest.param("request_capacity", id="requests"),
    ],
)
def test_a_legacy_account_is_given_no_ceiling_it_never_declared(ceiling: str) -> None:
    account = load_account_pool(_settings(), {}).account(_ZAI)

    assert account is not None and getattr(account, ceiling) is None


def test_an_ordinary_attempt_selects_the_account_it_always_did() -> None:
    response = _store(_settings()).resolve_and_mint(_request())

    assert response.decision.account_id == _ZAI


def test_an_ordinary_attempt_reports_no_fallback_lineage() -> None:
    decision = _store(_settings()).resolve_and_mint(_request()).decision

    assert (decision.fallback_position, decision.fallback_hops) == (0, 0)


def test_an_ordinary_attempt_passes_over_nobody() -> None:
    """A single-account lane has nothing to explain, so it explains nothing."""
    decision = _store(_settings()).resolve_and_mint(_request()).decision

    assert decision.rejected_accounts == ()


def test_a_hop_has_nowhere_to_go_on_a_single_account_lane() -> None:
    """Even a perfectly formed citation cannot move a lane of one."""
    store = _store(_settings())
    first = store.resolve_and_mint(_request())

    second = store.resolve_and_mint(
        _request(
            mint_attempt_id="att-2",
            retry_of_mint_decision_id=first.decision.mint_decision_id,
        )
    )

    assert second.decision.outcome is not DecisionOutcome.SELECTED


def test_a_deployment_may_refuse_every_hop_outright() -> None:
    assert _settings(max_fallback_hops=0).max_fallback_hops == 0


def test_the_shipped_default_permits_exactly_one_hop() -> None:
    """A ceiling, not a target: the smallest bound that still does something."""
    assert _settings().max_fallback_hops == 1


def test_a_deployment_declares_no_accounts_file_by_default() -> None:
    assert _settings().accounts_file is None


# -- and the contrast, so none of the above is vacuous -----------------------


def test_an_accounts_file_actually_adds_a_second_candidate(tmp_path: Path) -> None:
    path = tmp_path / "accounts.yaml"
    path.write_text(_DOCUMENT, encoding="utf-8")
    pool = load_account_pool(
        _settings(accounts_file=path),
        {"GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY": "declared-key"},
    )

    assert pool.candidates_for_model("glm-5.3") == (_ZAI, _SECONDARY)


def test_a_declared_account_never_displaces_the_one_already_serving(
    tmp_path: Path,
) -> None:
    """Adding a backup must not silently promote it over today's primary."""
    path = tmp_path / "accounts.yaml"
    path.write_text(_DOCUMENT, encoding="utf-8")
    store = _store(
        _settings(accounts_file=path),
        {"GATEWAY_ACCOUNT_ZAI_SECONDARY_KEY": "declared-key"},
    )

    assert store.resolve_and_mint(_request()).decision.account_id == _ZAI
