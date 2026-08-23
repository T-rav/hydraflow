"""The canary's two provable properties (ADR-0141): bounded, and reversible.

Bounded — the predicate answers "no" for every repository but one, for every
transport but the gateway, and for every identity that is not exactly canonical.
Reversible — one empty config field puts every one of those answers back to "no"
without touching a policy, a snapshot, or the gateway.
"""

from __future__ import annotations

from pathlib import Path
from typing import Any

import pytest

from driver_contracts import ModelRequirementKind, WorkerRole
from hydraflow_gateway.routing_policy import (
    DecisionOutcome,
    LegacyRouteMechanism,
    PolicySnapshot,
    PolicySource,
    RequestFace,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    hash_policies,
)
from hydraflow_gateway.routing_store import RoutingPolicyStore
from route_enforcement import (
    EnforcedRoute,
    EnforcementRefused,
    canary_armed,
    canary_blast_radius,
    enforce_canary_route,
)
from route_shadow import RouteStage, policy_snapshot_path, record_route_shadow

_CANARY = "acme/project-x"


class _Config:
    """The narrow slice of ``HydraFlowConfig`` this seam reads."""

    def __init__(self, root: Path, **overrides: Any) -> None:
        self.repo_data_root = root
        self.repo = _CANARY
        self.repo_slug = "acme-project-x"
        self.gateway_repo_class = "hydraflow"
        self.gateway_enforcement_canary_repo = _CANARY
        self.gateway_capture_bodies = False
        self.gateway_route_shadow_enabled = True
        for key, value in overrides.items():
            setattr(self, key, value)


def _stages(provider: str) -> tuple[RouteStage, ...]:
    return (
        RouteStage(
            mechanism=LegacyRouteMechanism.FLEET_RATCHET,
            provider=provider,
            detail="gateway_fleet_ratchet_enabled=true",
        ),
    )


def _zai_policy() -> RoutingPolicy:
    """ "Project X always uses z.ai" — the canary's one rule.

    Both mappings are deliberate. ``provider_lock`` alone cannot move a spawn
    that asked for a Claude model by name: ADR-0139 §D4 refuses to substitute
    silently, so an operator has to say which model answers each request. The
    capability entry answers a spawn that named no model; the concrete entry
    answers the ones HydraFlow's agentic seams actually spawn with.
    """
    return RoutingPolicy(
        id="project-x-zai",
        match=RoutingMatch(repo_ids=(_CANARY,)),
        action=RoutingAction(
            provider_lock="zai-harness",
            requirement_map=(
                {
                    "requirement": {"kind": "capability", "value": "balanced"},
                    "effective_model": "glm-5.3",
                },
                {
                    "requirement": {
                        "kind": "concrete_model",
                        "value": "claude-sonnet-4-6",
                    },
                    "effective_model": "glm-5.3",
                },
            ),
        ),
    )


@pytest.fixture(autouse=True)
def _zai_account_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """The canary locks to z.ai, and an unconfigured account is never eligible."""
    monkeypatch.setenv("ZAI_API_KEY", "test-key")


def _snapshot() -> PolicySnapshot:
    policies = (_zai_policy(),)
    return PolicySnapshot(
        revision=1, policies=policies, content_hash=hash_policies(policies)
    )


def _write_policies(root: Path, *policies: RoutingPolicy) -> None:
    config = _Config(root)
    RoutingPolicyStore(policy_snapshot_path(config)).save(list(policies))


def _enforce(config: _Config, **overrides: Any) -> EnforcedRoute | None:
    kwargs: dict[str, Any] = {
        "config": config,
        "principal_id": "implementer",
        "stages": _stages("gateway"),
        "final_provider": "gateway",
        "final_model": "claude-sonnet-4-6",
        "request_face": RequestFace.AGENTIC,
    }
    kwargs.update(overrides)
    return enforce_canary_route(**kwargs)


# --------------------------------------------------------------------------
# Reversible in one action: the default is off, and clearing it is the rollback
# --------------------------------------------------------------------------


@pytest.mark.parametrize(
    "value",
    [
        pytest.param("", id="the-unset-default-arms-nothing"),
        pytest.param("   ", id="whitespace-is-not-a-repository"),
        pytest.param("acme-project-x", id="a-lossy-runtime-slug-arms-nothing"),
        pytest.param("acme/project x", id="an-unsafe-segment-arms-nothing"),
        pytest.param("a/b/c", id="two-slashes-are-not-owner-slash-repo"),
    ],
)
def test_the_canary_is_disarmed_unless_one_exact_repository_is_named(
    tmp_path: Path, value: str
) -> None:
    """The dial is the switch: anything that is not a canonical repo is off."""
    assert (
        canary_armed(_Config(tmp_path, gateway_enforcement_canary_repo=value)) is False
    )


def test_a_canonical_repository_arms_the_canary(tmp_path: Path) -> None:
    """The affirmative case, so every disarmed assertion above is not vacuous."""
    assert canary_armed(_Config(tmp_path)) is True


def test_a_disarmed_canary_enforces_nothing_even_with_a_policy(
    tmp_path: Path,
) -> None:
    """The off-switch restores prior behaviour without touching the policy set."""
    _write_policies(tmp_path, _zai_policy())
    config = _Config(tmp_path, gateway_enforcement_canary_repo="")

    assert _enforce(config) is None


def test_a_config_without_the_dial_at_all_enforces_nothing(tmp_path: Path) -> None:
    """A config predating this phase must not become enforced by upgrading."""
    config = _Config(tmp_path)
    del config.gateway_enforcement_canary_repo
    _write_policies(tmp_path, _zai_policy())

    assert _enforce(config) is None


# --------------------------------------------------------------------------
# Bounded blast radius: everything outside the slice answers "no"
# --------------------------------------------------------------------------


def test_another_repository_is_outside_the_canary(tmp_path: Path) -> None:
    """The canary names one repository, and it is not this one."""
    _write_policies(tmp_path, _zai_policy())
    config = _Config(tmp_path, repo="acme/other")

    assert _enforce(config) is None


def test_a_repository_known_only_by_its_lossy_slug_is_outside(tmp_path: Path) -> None:
    """ADR-0139 §D2: a slug can never join, so it can never be enforced."""
    _write_policies(tmp_path, _zai_policy())
    config = _Config(tmp_path, repo="acme-project-x")

    assert _enforce(config) is None


@pytest.mark.parametrize(
    "provider",
    [
        pytest.param("claude", id="a-direct-anthropic-spawn-is-ungoverned-traffic"),
        pytest.param("zai", id="a-direct-zai-harness-spawn-is-ungoverned-traffic"),
    ],
)
def test_a_spawn_that_never_reaches_the_gateway_is_outside(
    tmp_path: Path, provider: str
) -> None:
    """Policy binds what transits the tap; the canary never promotes traffic onto it."""
    _write_policies(tmp_path, _zai_policy())

    assert (
        _enforce(_Config(tmp_path), stages=_stages(provider), final_provider=provider)
        is None
    )


def test_the_blast_radius_names_every_route_the_canary_moves(tmp_path: Path) -> None:
    """``diff_matrices`` answers the operator's question before the first spawn."""
    moved = canary_blast_radius(config=_Config(tmp_path), snapshot=_snapshot())

    assert {diff.after.decision.effective_model for diff in moved if diff.after} == {
        "glm-5.3"
    }


def test_an_empty_snapshot_moves_no_route_at_all(tmp_path: Path) -> None:
    """Arming the canary on a repository with no policy changes nothing."""
    assert (
        canary_blast_radius(config=_Config(tmp_path), snapshot=PolicySnapshot.empty())
        == ()
    )


def test_the_blast_radius_of_a_disarmed_canary_is_empty(tmp_path: Path) -> None:
    """A policy that exists but is not armed moves nothing, and says so."""
    assert (
        canary_blast_radius(
            config=_Config(tmp_path, gateway_enforcement_canary_repo=""),
            snapshot=_snapshot(),
        )
        == ()
    )


# --------------------------------------------------------------------------
# Inside the slice: the decision starts changing what gets spawned
# --------------------------------------------------------------------------


def test_a_managed_policy_supplies_the_effective_model(tmp_path: Path) -> None:
    """The moment enforcement becomes real."""
    _write_policies(tmp_path, _zai_policy())

    route = _enforce(_Config(tmp_path))

    assert route is not None
    assert route.effective_model == "glm-5.3"


def test_a_managed_policy_rewrites_the_child_command(tmp_path: Path) -> None:
    """AC4: the spawn actually runs on the model the decision returned."""
    _write_policies(tmp_path, _zai_policy())
    route = _enforce(_Config(tmp_path))

    assert route is not None
    assert route.apply_to_command(["claude", "-p", "--model", "claude-sonnet-4-6"]) == [
        "claude",
        "-p",
        "--model",
        "glm-5.3",
    ]


def test_an_unmanaged_route_leaves_the_command_byte_identical(tmp_path: Path) -> None:
    """No policy claims this context, so the canary changes not one argument."""
    _write_policies(tmp_path)
    route = _enforce(_Config(tmp_path))
    cmd = ["claude", "-p", "--model", "claude-sonnet-4-6"]

    assert route is not None
    assert route.apply_to_command(cmd) == cmd


def test_an_unmanaged_route_reports_legacy_compatibility(tmp_path: Path) -> None:
    """It is still governed traffic — it just is not policy-chosen traffic."""
    _write_policies(tmp_path)
    route = _enforce(_Config(tmp_path))

    assert route is not None
    assert route.decision.policy_source is PolicySource.LEGACY_COMPATIBILITY


def test_a_corrupt_snapshot_refuses_the_spawn(tmp_path: Path) -> None:
    """Missing policy evidence never presents as a coherent 'no policy' state."""
    path = policy_snapshot_path(_Config(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(EnforcementRefused):
        _enforce(_Config(tmp_path))


def test_a_refusal_carries_the_decision_that_caused_it(tmp_path: Path) -> None:
    """An operator has to be able to read why a spawn was refused."""
    path = policy_snapshot_path(_Config(tmp_path))
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("{not json", encoding="utf-8")

    with pytest.raises(EnforcementRefused) as caught:
        _enforce(_Config(tmp_path))

    assert caught.value.decision.outcome is DecisionOutcome.HELD


def test_a_literal_family_under_a_provider_lock_refuses_rather_than_substituting(
    tmp_path: Path,
) -> None:
    """ADR-0139 §D4 at the spawn seam: an Opus request never silently becomes GLM."""
    _write_policies(tmp_path, _zai_policy())

    with pytest.raises(EnforcementRefused):
        _enforce(_Config(tmp_path), final_model="opus")


def test_an_unmapped_claude_model_under_a_provider_lock_refuses(
    tmp_path: Path,
) -> None:
    """A named Claude model is never quietly served by the locked z.ai lane."""
    _write_policies(tmp_path, _zai_policy())

    with pytest.raises(EnforcementRefused):
        _enforce(_Config(tmp_path), final_model="claude-haiku-4-5")


def test_a_refused_spawn_is_refused_before_any_credential_exists(
    tmp_path: Path,
) -> None:
    """AC5: a held route cannot fall through to an ambient credential.

    ``enforce_canary_route`` runs before ``resolve_harness_env``, so a refusal
    means the spawn never reaches a mint at all — proven here by there being no
    route object to hand one.
    """
    _write_policies(tmp_path, _zai_policy())

    with pytest.raises(EnforcementRefused) as caught:
        _enforce(_Config(tmp_path), final_model="opus")

    assert caught.value.decision.outcome is not DecisionOutcome.SELECTED


def test_the_route_carries_the_requirement_the_spawn_actually_asked_for(
    tmp_path: Path,
) -> None:
    """The mint states an intent, so the intent must survive the resolve."""
    _write_policies(tmp_path, _zai_policy())
    route = _enforce(_Config(tmp_path))

    assert route is not None
    assert route.requirement.kind is ModelRequirementKind.CONCRETE_MODEL


def test_the_route_carries_the_canonical_role_when_the_principal_names_one(
    tmp_path: Path,
) -> None:
    """ADR-0138 §D6's exact join, reused rather than re-derived."""
    _write_policies(tmp_path, _zai_policy())
    route = _enforce(_Config(tmp_path))

    assert route is not None
    assert route.worker_role is WorkerRole.IMPLEMENTER


def test_a_loop_principal_carries_no_invented_role(tmp_path: Path) -> None:
    """A loop name is not a WorkerRole, and guessing one would route on a guess."""
    _write_policies(tmp_path, _zai_policy())
    route = _enforce(_Config(tmp_path), principal_id="adr_reviewer")

    assert route is not None
    assert route.worker_role is None


def test_each_resolve_mints_its_own_attempt_identity(tmp_path: Path) -> None:
    """A reused attempt id would be read by the gateway as a retry, not a spawn."""
    _write_policies(tmp_path, _zai_policy())
    first = _enforce(_Config(tmp_path))
    second = _enforce(_Config(tmp_path))

    assert first is not None
    assert second is not None
    assert first.mint_attempt_id != second.mint_attempt_id


def test_the_one_shot_face_inside_the_canary_is_enforced_too(tmp_path: Path) -> None:
    """A gateway one-shot is the same HTTP face; leaving it unbound would be a hole."""
    _write_policies(tmp_path, _zai_policy())

    assert _enforce(_Config(tmp_path), request_face=RequestFace.ONE_SHOT) is not None


# --------------------------------------------------------------------------
# AC8 — the enforced route and the shadow record name the same decision
# --------------------------------------------------------------------------


def test_the_shadow_record_and_the_enforced_route_share_one_decision_id(
    tmp_path: Path,
) -> None:
    """The join between the child's own chain and the gateway's ledger row.

    ``decision_id`` is content-addressed over the context and the snapshot
    (ADR-0139), so the observation and the enforcement of ONE spawn derive the
    same id independently. That is what lets a ledger row carrying
    ``route_decision_id`` be traced back to the hash-linked record of why the
    spawn routed where it did — without either side inventing an identity.
    """
    config = _Config(tmp_path)
    _write_policies(tmp_path, _zai_policy())
    recorded = record_route_shadow(
        config=config,
        principal_id="implementer",
        stages=_stages("gateway"),
        final_provider="gateway",
        final_model="claude-sonnet-4-6",
        request_face=RequestFace.AGENTIC,
    )
    route = _enforce(config)

    assert recorded is not None
    assert route is not None
    assert recorded.proposed.decision_id == route.decision.decision_id


def test_the_dial_the_predicate_reads_is_declared_on_the_real_config() -> None:
    """``canary_repo`` reads the dial by ``getattr`` with an empty default.

    That default is deliberate — an absent dial disarms, which is the safe
    direction, and ``test_a_config_without_the_dial_at_all_enforces_nothing``
    pins it. Its cost is that renaming the field on ``HydraFlowConfig`` would
    silently disarm the canary everywhere while every test above kept passing,
    because they all use a stub config. This is the assertion that notices.
    """
    from config import HydraFlowConfig

    assert "gateway_enforcement_canary_repo" in HydraFlowConfig.model_fields
