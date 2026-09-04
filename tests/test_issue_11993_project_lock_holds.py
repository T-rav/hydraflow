"""#11993 (Gateway P6d): "project X always uses z.ai" is demonstrably true.

The epic's whole promise stated as one sentence. This is a **demonstration**,
not a mechanism: it has no code of its own and proves that what P6b migrated
and P6c enforced actually holds, asserted against already-merged behaviour so
it is able to fail.

The two clauses that make it hard, and how each is discharged here:

**"including retries"** — a retry re-enters the spawn path and re-resolves. If
resolution were sensitive to anything but its inputs, attempt 2 could land
somewhere attempt 1 did not. `RouteDecision.decision_id` is content-addressed
(ADR-0139), so the proof is that repeated resolution of one context yields one
decision id — a drifting retry would produce a second.

**"including Fable children"** — a child that inherits nothing resolves on its
own defaults. `RouteContext` deliberately carries no lineage: the lock is a
property of the REPO, so every principal under it is covered whatever its
parentage. P6a's lineage is what makes a violation attributable in the ledger;
what makes it *fail* is that no principal id can escape the repo's policy.

**Anti-vacuity.** Every assertion here checks the `DecisionReason`, not just
the provider string. A test that passed because the request never constructed
would report the same green as one that passed because routing worked — that
exact failure has shipped in this repo (a catalogue-flag change vacated
role-as-probe tests). The unlocked control at the bottom is the other half:
with the policy removed the same request resolves to **anthropic**, so a green
here cannot come from a fixture that was never going to reach Anthropic anyway.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from driver_contracts import WorkerRole  # noqa: E402
from hydraflow_gateway.models import ProviderBinding, RepoClass  # noqa: E402
from hydraflow_gateway.routing_policy import (  # noqa: E402
    AccountAvailability,
    DecisionOutcome,
    DecisionReason,
    LegacyRoute,
    LegacyRouteMechanism,
    ModelRequirement,
    ModelRequirementKind,
    PolicySnapshot,
    RepoIdentity,
    RequestFace,
    RequirementMapping,
    RouteContext,
    RouteTransport,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    explain,
    hash_policies,
)

#: The repository the epic names. A lock is a property of the repo, which is
#: why every principal under it is in scope without enumerating principals.
_LOCKED_REPO = "acme/project-x"

_ANTHROPIC = AccountAvailability(
    account_id="legacy-anthropic",
    provider_binding=ProviderBinding.ANTHROPIC,
    configured=True,
)
_ZAI = AccountAvailability(
    account_id="legacy-zai-harness",
    provider_binding=ProviderBinding.ZAI_HARNESS,
    configured=True,
)

_CONCRETE_GLM = ModelRequirement(
    kind=ModelRequirementKind.CONCRETE_MODEL, value="glm-5.2"
)
_HIGH_REASONING = ModelRequirement(
    kind=ModelRequirementKind.CAPABILITY, value="high-reasoning"
)
_LITERAL_OPUS = ModelRequirement(
    kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-opus"
)
_LITERAL_SONNET = ModelRequirement(
    kind=ModelRequirementKind.LITERAL_FAMILY, value="claude-sonnet"
)

#: The legacy route the decision would fall back to. Anthropic on purpose: if
#: the lock ever stops applying, the fallback is the wrong lane, so a silent
#: failure is visible as a provider change rather than as an error.
_LEGACY = LegacyRoute(
    provider_binding=ProviderBinding.ANTHROPIC,
    account_id="legacy-anthropic",
    model="claude-opus-4-8",
    transport=RouteTransport.GATEWAY,
    mechanism=LegacyRouteMechanism.DEFAULT,
    mechanism_detail="default=claude",
)


def _context(**overrides: object) -> RouteContext:
    base: dict[str, object] = {
        "repo": RepoIdentity.from_canonical(_LOCKED_REPO),
        "repo_class": RepoClass.CLIENT,
        "principal_id": "implementer",
        "worker_role": WorkerRole.IMPLEMENTER,
        "model_requirement": _CONCRETE_GLM,
        "request_face": RequestFace.AGENTIC,
        "accounts": (_ANTHROPIC, _ZAI),
        "legacy_route": _LEGACY,
    }
    base.update(overrides)
    return RouteContext(**base)  # type: ignore[arg-type]


def _snapshot(*policies: RoutingPolicy) -> PolicySnapshot:
    return PolicySnapshot(
        revision=7, policies=policies, content_hash=hash_policies(policies)
    )


def _zai_lock() -> RoutingPolicy:
    """The declaration an operator writes: this project always uses z.ai."""
    return RoutingPolicy(
        id="project-x-zai",
        priority=100,
        match=RoutingMatch(repo_ids=(_LOCKED_REPO,)),
        action=RoutingAction(
            provider_lock=ProviderBinding.ZAI_HARNESS,
            requirement_map=(
                RequirementMapping(
                    requirement=_HIGH_REASONING, effective_model="glm-5.3"
                ),
            ),
            allowed_patterns=("glm-*",),
        ),
    )


def _locked(**overrides: object):
    return explain(_context(**overrides), _snapshot(_zai_lock()))


class TestTheDeclaredAgenticScopeIsEntirelyOnZai:
    """AC1: every role in the scope, not a sampled call."""

    def test_the_scope_is_not_empty(self) -> None:
        """Anti-vacuity floor: the parametrised cases below are all trivially
        true against an empty enumeration."""
        assert len(tuple(WorkerRole)) >= 7

    @pytest.mark.parametrize("role", list(WorkerRole), ids=lambda r: r.value)
    def test_every_worker_role_resolves_to_zai(self, role: WorkerRole) -> None:
        """Enumerated from `WorkerRole` by reference, so a role added tomorrow
        is covered without anyone remembering this file."""
        decision = _locked(worker_role=role, principal_id=role.value)

        assert decision.outcome is DecisionOutcome.SELECTED
        assert decision.reason is DecisionReason.MATCHED_POLICY
        assert decision.provider_binding is ProviderBinding.ZAI_HARNESS

    @pytest.mark.parametrize(
        "face",
        list(RequestFace),
        ids=lambda f: f.value,
    )
    def test_every_request_face_resolves_to_zai(self, face: RequestFace) -> None:
        """A lock that only held for the agentic face would leak one-shot calls."""
        decision = _locked(request_face=face)

        assert decision.provider_binding is ProviderBinding.ZAI_HARNESS
        assert decision.reason is DecisionReason.MATCHED_POLICY

    def test_a_capability_request_is_mapped_onto_a_glm_model(self) -> None:
        """The operator's explicit mapping is what moves a capability request."""
        decision = _locked(model_requirement=_HIGH_REASONING)

        assert decision.provider_binding is ProviderBinding.ZAI_HARNESS
        assert decision.effective_model == "glm-5.3"


class TestARetryStaysOnZai:
    """AC2: the assertion covers every attempt, not just the first."""

    def test_repeated_resolution_yields_one_decision(self) -> None:
        """A retry re-enters the spawn path and resolves again.

        `decision_id` is content-addressed, so identical inputs must produce
        one id. A second id would mean resolution depends on something other
        than its inputs — which is exactly how attempt 2 lands somewhere
        attempt 1 did not.
        """
        ids = {_locked().decision_id for _ in range(8)}

        assert len(ids) == 1

    def test_every_attempt_binds_zai(self) -> None:
        """Stated as the property the retry clause actually cares about."""
        attempts = [_locked() for _ in range(8)]

        assert {d.provider_binding for d in attempts} == {ProviderBinding.ZAI_HARNESS}
        assert {d.reason for d in attempts} == {DecisionReason.MATCHED_POLICY}


class TestFableChildrenStayOnZai:
    """AC3: a child that inherits nothing still cannot escape the lock."""

    @pytest.mark.parametrize(
        "principal_id",
        [
            pytest.param("fable-driver", id="driver"),
            pytest.param("fable-driver/child-1", id="child"),
            pytest.param("fable-driver/child-1/grandchild", id="grandchild"),
            pytest.param("subagent:reviewer", id="subagent"),
        ],
    )
    def test_a_child_principal_resolves_to_zai(self, principal_id: str) -> None:
        """The lock is a property of the REPO, not of the principal.

        `RouteContext` carries no lineage on purpose: a child resolving "on its
        own defaults" is still resolving under its repository's policy, so
        there is no principal id that escapes. P6a's lineage is what makes a
        violation attributable in the ledger; this is what stops there being
        one to attribute.
        """
        decision = _locked(principal_id=principal_id)

        assert decision.provider_binding is ProviderBinding.ZAI_HARNESS
        assert decision.reason is DecisionReason.MATCHED_POLICY


class TestALockRefusesRatherThanDowngrades:
    """AC4: the epic's stated non-negotiable.

    A literal Opus/Sonnet request is a request for a *specific model family*.
    Serving it from GLM would be the "GLM reported as a Claude model" hazard:
    the caller believes it got what it asked for. The lock must refuse.
    """

    @pytest.mark.parametrize(
        "requirement",
        [
            pytest.param(_LITERAL_OPUS, id="opus"),
            pytest.param(_LITERAL_SONNET, id="sonnet"),
        ],
    )
    def test_a_literal_family_is_never_served_from_zai(
        self, requirement: ModelRequirement
    ) -> None:
        decision = _locked(model_requirement=requirement)

        assert decision.outcome is not DecisionOutcome.SELECTED
        assert decision.reason is DecisionReason.LITERAL_FAMILY_UNSATISFIABLE
        assert decision.provider_binding is not ProviderBinding.ZAI_HARNESS

    @pytest.mark.parametrize(
        "requirement",
        [
            pytest.param(_LITERAL_OPUS, id="opus"),
            pytest.param(_LITERAL_SONNET, id="sonnet"),
        ],
    )
    def test_no_glm_model_is_handed_back_for_a_literal_family(
        self, requirement: ModelRequirement
    ) -> None:
        """The downgrade, stated as the thing that must not appear.

        Asserting only the outcome would still pass if a refused decision
        carried a glm model in `effective_model` for a caller to pick up.
        """
        effective = _locked(model_requirement=requirement).effective_model

        assert effective is None or not effective.lower().startswith("glm")


class TestTheLockIsWhatDoesTheWork:
    """The control. Without it, every assertion above is unfalsifiable."""

    def test_without_the_policy_the_same_request_reaches_anthropic(self) -> None:
        """Remove the lock and the identical context resolves to the OTHER lane.

        This is what makes the suite above evidence rather than decoration: if
        the fixture could never have reached Anthropic, "always z.ai" would be
        true of a request that had nowhere else to go.
        """
        decision = explain(_context(), _snapshot())

        assert decision.provider_binding is ProviderBinding.ANTHROPIC
        assert decision.reason is DecisionReason.NO_POLICY_APPLIES

    def test_a_lock_naming_another_repo_does_not_apply(self) -> None:
        """Decoy: the match is on the repo, so a lock elsewhere must not bind."""
        elsewhere = RoutingPolicy(
            id="other-project-zai",
            priority=100,
            match=RoutingMatch(repo_ids=("acme/other-project",)),
            action=RoutingAction(provider_lock=ProviderBinding.ZAI_HARNESS),
        )

        decision = explain(_context(), _snapshot(elsewhere))

        assert decision.provider_binding is ProviderBinding.ANTHROPIC
