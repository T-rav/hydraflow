"""A generated provider lock refuses a literal Anthropic model (#11993 AC4).

The epic's stated non-negotiable: "a literal Opus/Sonnet requirement is NEVER
silently rewritten to GLM — a lock must refuse, not downgrade." That is already
asserted for hand-written policies in `tests/test_routing_policy.py`. It has
never been asserted for the policies P6b's migration *generates*, which are the
ones a repository will actually be running.

It holds today by construction rather than by intent: `baseline_policies` emits
a `provider_lock` and no `requirement_map`, and `anthropic_lane_required` refuses
to move a literal family off the Anthropic lane unless a mapping says so out
loud. Nothing stops a future generator from adding that mapping — which would
turn a refusal into a silent downgrade, on the one property the epic calls
non-negotiable. So it is pinned against the generator's real output.

Per the issue's own anti-vacuity note, the assertions are on the **reason**.
A test that passed because the request never constructed would report the same
green as one that passed because routing refused, and that exact failure has
shipped here before.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import HydraFlowConfig  # noqa: E402
from hydraflow_gateway.routing_policy import (  # noqa: E402
    DecisionOutcome,
    DecisionReason,
    ModelRequirementKind,
    PolicySnapshot,
    RequestFace,
    explain,
)
from route_shadow import (  # noqa: E402
    LegacyRouteMechanism,
    RouteStage,
    build_route_context,
)
from routing_baseline import baseline_policies  # noqa: E402

_REPO = "acme/hydraflow"
_GLM = "glm-5.2"

#: Both halves of the epic's phrase, so neither is covered by the other.
_LITERALS = ("claude-opus-4-1", "claude-sonnet-4-6")


@pytest.fixture(autouse=True)
def _zai_account_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """Without a credential the resolver holds for an unrelated reason."""
    monkeypatch.setenv("ZAI_API_KEY", "generated-lock-refusal-key")


def _locked_config() -> HydraFlowConfig:
    """A repo whose planner dial is locked to the GLM lane."""
    return HydraFlowConfig(repo=_REPO, planner_provider="zai", planner_model=_GLM)


def _decide(model: str):
    """Resolve a planner spawn asking for *model* against the generated lock."""
    config = _locked_config()
    context = build_route_context(
        config=config,
        principal_id="planner",
        final_provider="claude",
        final_model=model,
        request_face=RequestFace.AGENTIC,
        stages=(
            RouteStage(
                mechanism=LegacyRouteMechanism.ROLE_DIAL,
                provider="claude",
                detail=f"planner_provider=zai, requested {model}",
            ),
        ),
    )
    return context, explain(context, PolicySnapshot(policies=baseline_policies(config)))


def test_the_generator_actually_produced_a_lock() -> None:
    """Anti-vacuity floor: every refusal below is trivial against no policy."""
    policies = baseline_policies(_locked_config())

    assert [p.id for p in policies] == ["baseline-planner-provider"]
    assert policies[0].action.provider_lock is not None
    assert policies[0].action.requirement_map == (), (
        "the generator grew a requirement_map — that is the mechanism by which "
        "a lock stops refusing and starts downgrading; see this file's docstring"
    )


@pytest.mark.parametrize("model", _LITERALS)
def test_a_literal_anthropic_request_is_refused_not_downgraded(model: str) -> None:
    """The non-negotiable, asserted on the REASON rather than the provider."""
    _, decision = _decide(model)

    assert (decision.outcome, decision.reason) == (
        DecisionOutcome.HELD,
        DecisionReason.LITERAL_FAMILY_UNSATISFIABLE,
    )


@pytest.mark.parametrize("model", _LITERALS)
def test_the_refusal_hands_back_no_model_at_all(model: str) -> None:
    """A held decision that still named a model would be a downgrade in disguise.

    The outcome and reason above say the resolver refused; these say it did not
    also quietly publish a GLM model for a caller to use anyway.
    """
    _, decision = _decide(model)

    assert (decision.provider_binding, decision.effective_model) == (None, None)


@pytest.mark.parametrize("model", _LITERALS)
def test_the_request_really_was_for_an_anthropic_literal(model: str) -> None:
    """Proves the refusals above are about the literal, not about a broken context.

    The issue's anti-vacuity note names this exact shape: a request that never
    constructed reports the same green as one that routed correctly.
    """
    context, _ = _decide(model)

    assert context.model_requirement.kind in {
        ModelRequirementKind.CONCRETE_MODEL,
        ModelRequirementKind.LITERAL_FAMILY,
    }
    assert context.model_requirement.value == model


def test_a_glm_request_against_the_same_lock_is_served() -> None:
    """The contrast that makes the refusals meaningful rather than universal.

    Without this, a generator emitting a policy that matched nothing at all
    would satisfy every assertion above.
    """
    config = _locked_config()
    context = build_route_context(
        config=config,
        principal_id="planner",
        final_provider="zai",
        final_model=_GLM,
        request_face=RequestFace.AGENTIC,
        stages=(
            RouteStage(
                mechanism=LegacyRouteMechanism.ROLE_DIAL,
                provider="zai",
                detail="planner_provider=zai",
            ),
        ),
    )

    decision = explain(context, PolicySnapshot(policies=baseline_policies(config)))

    assert decision.outcome is DecisionOutcome.SELECTED
    assert decision.reason is DecisionReason.MATCHED_POLICY
