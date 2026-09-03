"""Generate the baseline routing policies a legacy `*_provider` dial implies.

P6b (#11991) migrates the dials into policy. This is the generator half: a pure
function from a repository's `HydraFlowConfig` to the policies that reproduce
what its dials do today. Nothing reads the result yet — the resolver switch and
the reversible down-path are separate, which is what makes this slice safely
revertible: deleting it changes no route.

Three properties decide whether the output is correct, and each is a constraint
discovered rather than assumed:

**A generated role policy must name its repository.** Precedence is structural
(`precedence_level` reads the dimensions a `match` names) and `_rank` compares
the rung before the priority, so a policy matching only `roles=[...]` earns
`GLOBAL_ROLE_OR_REQUIREMENT` (7) while a repo-wide `repo_provider` rule earns
`REPO_ANY_ROLE` (4). Lower wins, so the role dial would LOSE to the repo-wide
preference — the inverse of `role dial > repo_provider`, which `config.py`
documents. Naming the repo alongside the role earns `REPO_ROLE` (3) and
restores the order. See `TestThePolicyLadderInvertsTheLegacyOrder` (#12028).

**A dial still on its default emits nothing.** A dial nobody moved is reached
with no managed policy at all, and `explain` reports exactly that as
`legacy-compatibility`. Emitting a policy that re-states the default would
change the decision's *source* without changing its route, which is a behaviour
change dressed as a no-op. The default is read from the dial itself, so this
holds across ADR-0147's move from `claude` to `gateway` and any move after it.

**The dials this cannot express are a list, not a silence.** Two of the fourteen
have no expressible join today — `maintenance_provider` and `repo_provider`,
both because they are not role rules — and each is recorded in
`UNGENERATED_DIALS` with its reason. A generator that quietly skipped them
would look complete while leaving the two dials with the widest reach unmoved.
"""

from __future__ import annotations

from config import HydraFlowConfig
from hydraflow_gateway.routing_policy import (
    ProviderBinding,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    WorkerRole,
)


#: The provider value a dial carries when nobody has moved it.
#:
#: Read from the model rather than spelled out. It was the literal `"claude"`
#: until ADR-0147 moved every dial default to `gateway`, at which point a
#: fleet sitting entirely on its defaults generated twelve policies that each
#: re-stated the default -- the exact behaviour-change-dressed-as-a-no-op this
#: module exists to avoid. A per-dial lookup cannot fall out of step with the
#: dial it describes (docs/standards/parametrised_guards/).
def _dial_default(dial: str) -> str:
    """The declared default of *dial*, or `"claude"` if it declares none."""
    field = HydraFlowConfig.model_fields.get(dial)
    default = getattr(field, "default", None) if field is not None else None
    return str(default) if isinstance(default, str) and default else "claude"


#: Every routing dial, mapped to the `principal_id` set its spawns carry.
#:
#: `principal_ids`, not `roles`, and that is a correction (#11991). Three dials
#: were joined on `WorkerRole` because their runner names one — but a role is a
#: LOSSY projection of the principal: `canonical_worker_role` is an exact match
#: against ADR-0137's vocabulary, so `reviewer` resolves and `review_fixer` and
#: `verification_judge` do not. A `roles=[REVIEWER]` policy therefore claimed one
#: of `review_provider`'s three spawn sites and left the other two on the legacy
#: path — one dial, split silently down the middle. `planner_provider` had the
#: same hole for `planner-gap-review`.
#:
#: Match dimensions AND (`evaluate_match` yields a rejection per unsatisfied
#: dimension), so naming both `roles` and `principal_ids` would NARROW to their
#: intersection rather than widen. One dimension, complete sets.
#:
#: Provenance: read off the `event_data["source"]` / `source=` literal at each
#: spawn, which `base_runner` turns into `principal_id`
#: (`principal_id = str(event_data.get("source", self._phase_name))`).
#: `test_every_declared_principal_exists_in_the_tree` fails if one is renamed.
_PRINCIPAL_DIALS: dict[str, frozenset[str]] = {
    "ac_provider": frozenset({"ac_generator", "ac_precheck", "ac_precheck_debug"}),
    "adr_review_provider": frozenset({"adr_reviewer", "decomposition_ensemble"}),
    "implementation_provider": frozenset({"implementer"}),
    "planner_provider": frozenset({"planner", "planner-gap-review"}),
    "pr_unstick_provider": frozenset({"pr_unsticker"}),
    "retro_finder_provider": frozenset({"retro_finder"}),
    "review_provider": frozenset({"reviewer", "review_fixer", "verification_judge"}),
    "term_proposer_provider": frozenset({"term_proposer"}),
    "transcript_summary_provider": frozenset({"transcript_summary"}),
    "triage_honeypot_provider": frozenset({"triage_honeypot"}),
    "triage_provider": frozenset({"triage"}),
    "wiki_compilation_provider": frozenset({"wiki_compilation"}),
}

#: Every dial this generator cannot express yet, and why. Kept as data so the
#: gap is assertable: `test_every_dial_is_generated_or_registered` fails when a
#: fifteenth dial appears in neither map nor here.
UNGENERATED_DIALS: dict[str, str] = {
    "maintenance_provider": (
        "not a role rule — it is the value a caller naming NO provider "
        "inherits, so it becomes a default-rung policy, not a scoped one"
    ),
    "repo_provider": (
        "not a role rule — it is the repo-wide fallback the role dials must "
        "outrank, so it lands with the precedence work rather than here"
    ),
}


def baseline_policies(config: HydraFlowConfig) -> tuple[RoutingPolicy, ...]:
    """The policies reproducing *config*'s moved dials, ordered by id.

    Only dials moved off ``"claude"`` produce a policy: see the module docstring
    on why re-stating a default is a behaviour change, not a no-op.
    """
    repo = str(getattr(config, "repo", "") or "")
    if not repo:
        return ()

    policies: list[RoutingPolicy] = []
    for dial, principals in sorted(_PRINCIPAL_DIALS.items()):
        binding = _moved_binding(config, dial)
        if binding is not None:
            policies.append(
                _policy(
                    dial,
                    repo=repo,
                    binding=binding,
                    principal_ids=tuple(sorted(principals)),
                )
            )
    return tuple(policies)


def _moved_binding(config: HydraFlowConfig, dial: str) -> ProviderBinding | None:
    """The binding *dial* names, or ``None`` when it is still on its default."""
    default = _dial_default(dial)
    value = str(getattr(config, dial, default) or default)
    if value == default:
        return None
    return ProviderBinding.ZAI_HARNESS if value == "zai" else ProviderBinding.ANTHROPIC


def _policy(
    dial: str,
    *,
    repo: str,
    binding: ProviderBinding,
    roles: tuple[WorkerRole, ...] = (),
    principal_ids: tuple[str, ...] = (),
) -> RoutingPolicy:
    """One generated policy, always naming its repo — see the module docstring.

    The two join dimensions are separate typed parameters rather than one
    `**match_extra` mapping. A `dict[str, object]` unpacked into `RoutingMatch`
    is untypeable and needs an arg-type suppression, and this repo's
    suppressions ratchet only shrinks — so the shape needing no suppression is
    the shape to write.
    """
    return RoutingPolicy(
        id=f"baseline-{dial.replace('_', '-')}",
        match=RoutingMatch(repo_ids=(repo,), roles=roles, principal_ids=principal_ids),
        action=RoutingAction(provider_lock=binding),
    )
