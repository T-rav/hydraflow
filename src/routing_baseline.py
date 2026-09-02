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

**A dial still on its default emits nothing.** The legacy route for a
`"claude"` dial is the Anthropic lane reached with no managed policy at all, and
`explain` reports exactly that as `legacy-compatibility`. Emitting a policy that
re-states the default would change the decision's *source* without changing its
route, which is a behaviour change dressed as a no-op.

**The dials this cannot express are a list, not a silence.** Six of the fourteen
have no expressible join today, for three different reasons, and each is
recorded in `UNGENERATED_DIALS` with which one. A generator that quietly skipped
them would look complete and migrate two thirds of the fleet.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from hydraflow_gateway.routing_policy import (
    ProviderBinding,
    RoutingAction,
    RoutingMatch,
    RoutingPolicy,
    WorkerRole,
)

if TYPE_CHECKING:
    from config import HydraFlowConfig

#: The provider value a dial carries when nobody has moved it.
_DEFAULT = "claude"

#: Dials whose spawn is a `BaseRunner` carrying a `PROVIDER_FIELD`, mapped to
#: the `WorkerRole` that runner takes. `triage_provider` is deliberately absent:
#: `WorkerRole` has no `triage` member, so it cannot join this way.
_ROLE_DIALS: dict[str, WorkerRole] = {
    "implementation_provider": WorkerRole.IMPLEMENTER,
    "planner_provider": WorkerRole.PLANNER,
    "review_provider": WorkerRole.REVIEWER,
}

#: Dials whose spawn goes through `run_lightweight_agent`, which passes
#: `principal_id=source`. Swept from the tree by #12023's source map; a dial can
#: govern more than one principal, so the value is a set.
_PRINCIPAL_DIALS: dict[str, frozenset[str]] = {
    "adr_review_provider": frozenset({"adr_reviewer", "decomposition_ensemble"}),
    "pr_unstick_provider": frozenset({"pr_unsticker"}),
    "retro_finder_provider": frozenset({"retro_finder"}),
    "transcript_summary_provider": frozenset({"transcript_summary"}),
    "wiki_compilation_provider": frozenset({"wiki_compilation"}),
}

#: Every dial this generator cannot express yet, and why. Kept as data so the
#: gap is assertable: `test_every_dial_is_generated_or_registered` fails when a
#: fifteenth dial appears in neither map nor here.
UNGENERATED_DIALS: dict[str, str] = {
    "triage_provider": (
        "no `WorkerRole.triage` exists to join on, and #12023 found triage.py's "
        "spawn carries source='triage_honeypot' — a different dial's principal"
    ),
    "triage_honeypot_provider": (
        "its spawn passes `source=source`, a parameter rather than a literal, "
        "so the principal is not knowable from the call site alone"
    ),
    "ac_provider": (
        "spawns through `stream_claude_with_telemetry`, not "
        "`run_lightweight_agent`, so it carries no `principal_id=source` to join"
    ),
    "term_proposer_provider": (
        "the dial is handed to a `ClaudeCLIClient` at construction; the "
        "principal belongs to whatever later invokes that client"
    ),
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
    for dial, role in sorted(_ROLE_DIALS.items()):
        binding = _moved_binding(config, dial)
        if binding is not None:
            policies.append(
                _policy(
                    dial, repo=repo, binding=binding, match_extra={"roles": (role,)}
                )
            )
    for dial, principals in sorted(_PRINCIPAL_DIALS.items()):
        binding = _moved_binding(config, dial)
        if binding is not None:
            policies.append(
                _policy(
                    dial,
                    repo=repo,
                    binding=binding,
                    match_extra={"principal_ids": tuple(sorted(principals))},
                )
            )
    return tuple(policies)


def _moved_binding(config: HydraFlowConfig, dial: str) -> ProviderBinding | None:
    """The binding *dial* names, or ``None`` when it is still on its default."""
    value = str(getattr(config, dial, _DEFAULT) or _DEFAULT)
    if value == _DEFAULT:
        return None
    return ProviderBinding.ZAI_HARNESS if value == "zai" else ProviderBinding.ANTHROPIC


def _policy(
    dial: str, *, repo: str, binding: ProviderBinding, match_extra: dict[str, object]
) -> RoutingPolicy:
    """One generated policy, always naming its repo — see the module docstring."""
    return RoutingPolicy(
        id=f"baseline-{dial.replace('_', '-')}",
        match=RoutingMatch(repo_ids=(repo,), **match_extra),  # type: ignore[arg-type]
        action=RoutingAction(provider_lock=binding),
    )
