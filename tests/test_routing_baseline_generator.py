"""#11991 AC1: a generated policy resolves to what its dial produced before.

The criterion is parity, and parity only means something when one side was
recorded against the *unmigrated* path. That side is
`tests/test_provider_dial_parity_baseline.py` (#12001/#12026/#12028); this file
is the other side — it drives the generated policies through the real resolver
(`explain`) and asserts the answer agrees.

Every expectation here is derived from `config.py` and `routing_baseline`'s own
maps rather than written out, for the reason #12001 gives: a hand-copied dial
list is one more place to forget the fifteenth dial, and forgetting it is
indistinguishable from the dial silently going unread.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config import _STAGE_PROVIDER_SOURCE, HydraFlowConfig  # noqa: E402
from hydraflow_gateway.routing_policy import (  # noqa: E402
    DecisionOutcome,
    PolicySnapshot,
    PolicySource,
    RequestFace,
    explain,
    precedence_level,
)
from route_shadow import (  # noqa: E402
    LegacyRouteMechanism,
    RouteStage,
    build_route_context,
    provider_binding_for,
)
from routing_baseline import (  # noqa: E402
    _PRINCIPAL_DIALS,
    _ROLE_DIALS,
    UNGENERATED_DIALS,
    baseline_policies,
)

_REPO = "acme/hydraflow"
_GLM = "glm-5.2"


@pytest.fixture(autouse=True)
def _zai_account_is_configured(monkeypatch: pytest.MonkeyPatch) -> None:
    """`local_account_availability` gates the zai account on a real credential.

    Without it the resolver HOLDS with `not-configured` — the correct answer,
    and one that would make every parity assertion below fail for a reason that
    has nothing to do with the generated policy. Setting the key puts the test
    in the state the dial itself requires: `apply_credit_failover` and
    `apply_repo_provider` both refuse to route to an endpoint with no key.
    """
    monkeypatch.setenv("ZAI_API_KEY", "baseline-generator-parity-key")


#: One principal per generatable dial. Role dials use the principal that
#: `canonical_worker_role` maps onto their role (exact match, ADR-0137);
#: principal dials use one of the sources #12023 swept for them.
_PRINCIPAL_FOR: dict[str, str] = {
    "implementation_provider": "implementer",
    "planner_provider": "planner",
    "review_provider": "reviewer",
    **{dial: sorted(sources)[0] for dial, sources in _PRINCIPAL_DIALS.items()},
}

_GENERATABLE = tuple(sorted({*_ROLE_DIALS, *_PRINCIPAL_DIALS}))

#: The one dial whose model is not `<dial>_model`. `_tool_model_stage_pairs`
#: pairs the `implementation` stage with the top-level `config.model`; there is
#: no `implementation_model` field at all. Written down rather than derived
#: because the pairing table holds values, not field names.
_MODEL_FIELD: dict[str, str] = {"implementation_provider": "model"}


def _config_with(dial: str, provider: str) -> HydraFlowConfig:
    """A config with *dial* moved, and its paired model moved with it.

    The zai backend only accepts `glm-*`, and `HydraFlowConfig` refuses the
    mismatch at construction — so moving a provider without its model is not a
    case this test could exercise even if it wanted to.
    """
    fields: dict[str, object] = {"repo": _REPO, dial: provider}
    if provider != "zai":
        return HydraFlowConfig(**fields)
    for name in _must_move_with(dial):
        if name in HydraFlowConfig.model_fields:
            fields[name] = "zai" if name.endswith("_provider") else _GLM
    return HydraFlowConfig(**fields)


def _must_move_with(dial: str) -> tuple[str, ...]:
    """Every field that has to move to the GLM lane when *dial* does.

    Derived from `_STAGE_PROVIDER_SOURCE`, not listed, and the derivation has
    two steps because a stage may have more than one source:

    * a stage inheriting from *dial* runs a glm model, so its `<stage>_model`
      moves — `review_provider` decides `subskill` and `debug`,
      `implementation_provider` decides `test_adequacy_verifier`;
    * a stage with a *second* source is validated against that source too, so
      the other dial must move as well. `subskill` and `debug` inherit from
      BOTH `ac_provider` and `review_provider`, which means neither of those
      dials can reach the GLM lane on its own.

    That second point is a property of the config, not of this test: a
    multi-source stage is jointly owned, and the migration has to express that
    as something other than one policy per dial.
    """
    names: list[str] = [_MODEL_FIELD.get(dial, dial.replace("_provider", "_model"))]
    for stage, sources in _STAGE_PROVIDER_SOURCE.items():
        if dial not in sources:
            continue
        names.append(f"{stage}_model")
        names.extend(other for other in sources if other != dial)
        names.extend(other.replace("_provider", "_model") for other in sources)
    return tuple(dict.fromkeys(names))


def _decide(config: HydraFlowConfig, dial: str, provider: str):
    """Resolve the generated policies for *dial* through the real resolver."""
    model = _GLM if provider == "zai" else "sonnet"
    context = build_route_context(
        config=config,
        principal_id=_PRINCIPAL_FOR[dial],
        final_provider=provider,
        final_model=model,
        request_face=RequestFace.AGENTIC,
        stages=(
            RouteStage(
                mechanism=LegacyRouteMechanism.ROLE_DIAL,
                provider=provider,
                detail=f"{dial}={provider}",
            ),
        ),
    )
    snapshot = PolicySnapshot(policies=baseline_policies(config))
    return explain(context, snapshot)


def test_the_dial_set_this_file_reasons_about_is_not_empty() -> None:
    """Anti-vacuity floor: every parametrised case below is trivial on ()."""
    assert len(_GENERATABLE) >= 8
    assert set(_PRINCIPAL_FOR) == set(_GENERATABLE)


@pytest.mark.parametrize("dial", _GENERATABLE)
@pytest.mark.parametrize("provider", ["zai", "gateway"])
def test_a_generated_policy_resolves_to_what_the_dial_produced(
    dial: str, provider: str
) -> None:
    """AC1 itself, against the resolver rather than against the generator."""
    config = _config_with(dial, provider)
    model = _GLM if provider == "zai" else "sonnet"

    decision = _decide(config, dial, provider)

    assert decision.provider_binding == provider_binding_for(provider, model), (
        f"{dial}={provider} resolved to {decision.provider_binding}, not the "
        f"binding the dial produces today"
    )


@pytest.mark.parametrize("dial", _GENERATABLE)
def test_a_managed_policy_claimed_the_route_not_the_legacy_fallback(dial: str) -> None:
    """The assertion above passes vacuously if no policy matched.

    `explain` reports the caller's own legacy route as `selected` with source
    `legacy-compatibility` when nothing claims the context — which agrees with
    the dial by construction and proves nothing about the generated policy.
    """
    decision = _decide(_config_with(dial, "zai"), dial, "zai")

    assert (decision.outcome, decision.policy_source) != (
        DecisionOutcome.SELECTED,
        PolicySource.LEGACY_COMPATIBILITY,
    ), f"no generated policy matched {dial}; the parity assertion is vacuous"
    assert decision.policy_id == f"baseline-{dial.replace('_', '-')}"


@pytest.mark.parametrize("dial", _GENERATABLE)
def test_every_generated_policy_outranks_a_repo_wide_rule(dial: str) -> None:
    """#12028's constraint, enforced on the generator's actual output.

    A role policy that failed to name its repo would earn rung 7 and lose to
    `repo_provider`'s rung 4 — inverting `role dial > repo_provider`, silently.
    """
    policies = baseline_policies(_config_with(dial, "zai"))

    assert policies, dial
    for policy in policies:
        assert int(precedence_level(policy)) < 4, (
            f"{policy.id} sits at rung {int(precedence_level(policy))}, which a "
            f"repo-wide `repo_provider` rule (rung 4) would outrank"
        )


def test_a_dial_on_its_default_generates_nothing() -> None:
    """Re-stating the default would change the decision's source, not its route."""
    assert baseline_policies(HydraFlowConfig(repo=_REPO)) == ()


def test_a_config_with_no_repo_generates_nothing() -> None:
    """Every generated policy names its repo; without one there is nothing to name."""
    assert baseline_policies(HydraFlowConfig()) == ()


def test_every_dial_is_either_generated_or_registered_as_a_gap() -> None:
    """The completeness guard: a fifteenth dial cannot be silently skipped.

    This is the whole reason `UNGENERATED_DIALS` is data. A generator that
    quietly emitted nothing for a dial it could not express would look complete
    while migrating two thirds of the fleet.
    """
    dials = {n for n in HydraFlowConfig.model_fields if n.endswith("_provider")}
    covered = {*_ROLE_DIALS, *_PRINCIPAL_DIALS, *UNGENERATED_DIALS}

    assert dials == covered, (
        f"unclassified dials: {sorted(dials - covered)}; "
        f"stale registrations: {sorted(covered - dials)}"
    )


def test_no_dial_is_both_generated_and_registered_as_a_gap() -> None:
    """A dial in both maps would read as covered while its reason said otherwise."""
    generated = {*_ROLE_DIALS, *_PRINCIPAL_DIALS}

    assert not (generated & set(UNGENERATED_DIALS))
