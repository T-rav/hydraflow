"""The brokered Plan canary's decision layer (#11541, ADR-0137 P3).

#11537 left a director that decides and a broker that admits, and deliberately
no code that dispatches. This module is the half of #11541 that decides *what*
would be dispatched and *whether this boundary is allowed to*; the half that
actually spawns a child is :mod:`plan_worker_runner`. Splitting them is not
tidiness — everything here is pure, so it is covered by the same source-level
no-authority guard the shadow decision path is, and the one module that can
reach a process stays the one module that is seam-declared.

Three separable decisions live here.

**The bound.** :func:`plan_canary_covers` is the only predicate that says a
boundary is inside the canary, and it demands all three of: the dial names one
canonical ``owner/repo``, this repository is exactly it, and the phase is
``PLAN``. "Implement, review and HITL remain Classic" is therefore a property
of one function rather than of every caller remembering to check. The shape is
lifted deliberately from ``route_enforcement.canary_covers`` (ADR-0141 D1),
including ADR-0139 D2's lossy-slug refusal in both directions: a slug typed
into the dial arms nothing, and a slug-derived repository cannot fall into an
armed canary.

**The tier choice.** :func:`resolve_plan_model` is where the broker starts
making a real model choice, and the whole of what it may depend on is two
things: the requirement the director asked for and the role's catalogued entry.
Not the issue text, not the time of day, not a previous decision — and not the
lane, which it deliberately does not ask about (see that function's docstring). The answer is a
:class:`PlanRouteDecision` carrying a content-addressed id, the rule that fired,
the source the tier came from, both revisions it was made against, and the input
echoed back — the same contract ``hydraflow_gateway.routing_policy.explain``
holds itself to, because a looser one produces a canary whose choices cannot be
explained after the fact.

**The latch.** :class:`PlanCanaryLatch` holds the issue's acceptance criterion
"initially one active Fable-directed issue per repository" as a fence rather
than as a convention.

A literal family **resolves literally or refuses**. There is no branch on which
``claude-opus`` is answered by a model without Anthropic provenance: the tier
table is code-owned and pinned by a test, and a lane that cannot serve Anthropic
at all rejects rather than substituting. That is the proposal's named hazard —
*"a GLM model is never reported as Sonnet"* — closed before a spawn rather than
at the receipt, where it would already have cost a worker.

Decision path, no authority. It may not spawn a process, mutate a label or
write convergence state -- pinned by
``tests/architecture/test_director_no_authority.py``, which requires this
sentence and this module's ``DECISION_PATH_MODULES`` entry to travel together
in both directions.
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum
from typing import TYPE_CHECKING

from driver_contracts import (
    LITERAL_FAMILIES,
    WORKER_CATALOG,
    DriverPhase,
    ModelRequirement,
    ModelRequirementKind,
    RejectionReason,
    WorkerRole,
)
from hydraflow_gateway.routing_policy import DecisionReason, canonicalize_repo

if TYPE_CHECKING:
    from datetime import datetime

    from config import HydraFlowConfig
    from driver_contracts import WorkerDispatchRequest

CANARY_PHASE = DriverPhase.PLAN
"""The one phase this canary may dispatch into. #11542 widens it, not a config."""

PLAN_TIER_CATALOG: dict[str, str] = {
    "claude-sonnet": "claude-sonnet-4-6",
    "claude-opus": "claude-opus-4-7",
}
"""Literal family -> the concrete model id that family resolves to.

Code-owned for the same reason ``WORKER_CATALOG`` is: a director selects from
it and cannot edit it, and an operator dial that could point a literal family
at an arbitrary id would be the one-field bypass of the provenance invariant
that ``WorkerDispatchRequest`` already refuses to allow a director.

``tests/test_plan_broker.py`` pins that every value here has Anthropic
provenance *and* satisfies its own family, so an edit that put ``glm-5.3`` under
``claude-opus`` fails at test time rather than at a receipt.
"""

CAPABILITY_TIERS: dict[str, str] = {
    "high-reasoning": "claude-opus",
    "balanced": "claude-sonnet",
}
"""Capability class -> the literal family that answers it in this canary.

The gateway resolver refuses an unmapped capability outright (ADR-0139:
*"guessing is how 'high-reasoning' silently becomes whatever the cheapest lane
happens to serve"*). This is the Plan canary's mapping, stated once, so the
choice between Sonnet and Opus is a table an operator can read rather than a
branch they have to trace.
"""


DIRECTOR_TURN_FAMILY = "claude-sonnet"
"""The family a *routed* director turn names for itself.

The director's own credential is ADR-0141 §D1's named gap, and closing it means
minting a route-**bound** key — which the gateway's data plane will only honour
if the child's request body names the exact model the binding does
(``governed_preflight.check_governed_body``). A CLI alias will not do: the CLI
resolves ``opus`` to a concrete id before the body leaves, so a binding written
against the alias is refused as ``model-not-bound``. So a routed director names
a concrete id, and it comes from this table rather than a second one for the
same reason everything else here does.

Sonnet rather than Opus because that is what an unrouted director turn already
runs on by default, and #11541 is not the place to silently re-tier the
observer while routing its key.
"""


def _catalog_revision() -> str:
    payload = json.dumps(
        {"tiers": PLAN_TIER_CATALOG, "capabilities": CAPABILITY_TIERS},
        sort_keys=True,
        separators=(",", ":"),
    )
    return f"sha256:{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"


PLAN_TIER_CATALOG_REVISION: str = _catalog_revision()
"""Content hash of both tables. A decision that cannot name the revision it was
made against cannot be replayed against it."""


class PlanRouteOutcome(StrEnum):
    """Exactly one disposition per resolution, in the resolver's vocabulary."""

    SELECTED = "selected"
    HELD = "held"
    """The request is right and something operational is missing. Retryable."""

    REJECTED = "rejected"
    """The request was inadmissible. Retrying it changes nothing."""


class PlanRouteRule(StrEnum):
    """Which resolution rule fired. Named so a decision can be replayed."""

    LITERAL_FAMILY_TO_CATALOGUED_ID = "literal-family-to-catalogued-id"
    CAPABILITY_CLASS_TO_FAMILY = "capability-class-to-family"
    NONE_MATCHED = "none-matched"


class PlanRouteSource(StrEnum):
    """Where the deciding fact came from."""

    DIRECTOR_LITERAL = "director-literal-family"
    """The director named the family; the broker only resolved it to an id."""

    CAPABILITY_TABLE = "capability-tier-table"
    """The director named a provider-neutral class; this table chose the tier."""

    NONE = "none"


class PlanRouteReason(StrEnum):
    """Why a resolution refused. Empty-equivalent (``NONE``) when selected."""

    NONE = "none"
    PHASE_NOT_PLAN = "phase-not-plan"
    ROLE_NOT_CATALOGUED_FOR_PLAN = "role-not-catalogued-for-plan"

    # #11542 widened the resolver to a second phase. The two refusals below are
    # the IMPLEMENT-phase counterparts of the two above, and they are separate
    # members rather than a shared "phase-not-covered" because they are what an
    # operator reads off a receipt: "this boundary was not a plan boundary" and
    # "this boundary was not an implement boundary" are different facts, and
    # collapsing them would make one refusal explain two different mistakes.
    PHASE_NOT_IMPLEMENT = "phase-not-implement"
    ROLE_NOT_CATALOGUED_FOR_IMPLEMENT = "role-not-catalogued-for-implement"

    # #11543 widened the resolver to a third phase, on the same rule as the two
    # above: an operator reads these off a receipt, and "this boundary was not a
    # review boundary" is a different fact from the other two. A shared
    # "phase-not-covered" member would make one refusal explain three different
    # mistakes, which is precisely what a deterministic reason code exists to
    # stop.
    PHASE_NOT_REVIEW = "phase-not-review"
    ROLE_NOT_CATALOGUED_FOR_REVIEW = "role-not-catalogued-for-review"
    LITERAL_FAMILY_UNSATISFIABLE = "literal-family-unsatisfiable"
    """The catalogued id does not satisfy the requirement it was resolved from.

    A **rejection**, not a hold, and the distinction is the one ADR-0141 D3
    draws: a held route is right with something operational missing, and would
    send an operator to fix a credential. This one is inadmissible — the tier
    table and the requirement disagree, which is a code defect rather than an
    operational gap, and retrying changes nothing.

    The *other* way a literal family becomes unsatisfiable — a
    ``provider_lock=zai-harness`` routing policy — is refused by the resolver
    at the spawn, on the far side of the trust boundary, and reaches the
    receipt through ``plan_worker_runner._refusal_for_spawn``.
    """

    CAPABILITY_UNMAPPED = "capability-unmapped"
    """A capability class with no tier. A HOLD: the table is the fixable thing."""

    CONCRETE_MODEL_REQUESTED = "concrete-model-requested"
    """Unreachable through ``WorkerDispatchRequest``, which refuses it outright.

    Kept because :func:`resolve_plan_model` is total and a total function that
    quietly returned ``SELECTED`` for a requirement kind it does not handle
    would be the silent-fallback shape (#10053) inside the resolver.
    """


#: The ``PHASE_NOT_*`` rows that still report ``ROLE_PHASE_FORBIDDEN``.
#:
#: ``driver_contracts.OUTSIDE_CANARY_BOUND`` asserts that the three
#: canary-bound situations must NOT share ``ROLE_PHASE_FORBIDDEN`` — a code
#: that says the CATALOGUE forbids the role, which is false of a phase that is
#: simply not the canary's. #11543 migrated the REVIEW row and deliberately
#: left the other two, because they belong to #11541/#11542's vocabulary.
#:
#: Named here, and referenced from the invariant's own docstring, because a
#: deliberate exception recorded only as a comment beside the rows is
#: indistinguishable from an unfinished migration: flipping either row
#: survived the suite in both directions (#11716). Shrink-only; empty is the
#: goal, and the row to migrate next is whichever phase's owner is in the file.
PHASE_ROWS_STILL_CONFLATED: frozenset[str] = frozenset(
    {"PHASE_NOT_PLAN", "PHASE_NOT_IMPLEMENT"}
)

#: Which deterministic receipt code each refusal reason reports.
#:
#: Lives beside the enum rather than in an actuator because there are now two
#: actuators bound to one vocabulary, and #11542 proved the hazard by adding two
#: members here and reddening the Plan actuator's own totality test. A table per
#: consumer is a drift waiting for the next phase; a table per *vocabulary* is
#: total by construction, and a new reason reddens one test rather than N.
REFUSAL_CODES: dict[PlanRouteReason, RejectionReason] = {
    PlanRouteReason.PHASE_NOT_PLAN: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_PLAN: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.PHASE_NOT_IMPLEMENT: RejectionReason.ROLE_PHASE_FORBIDDEN,
    PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_IMPLEMENT: (
        RejectionReason.ROLE_PHASE_FORBIDDEN
    ),
    # Not ROLE_PHASE_FORBIDDEN: this member says the PHASE is not the canary's,
    # which is silent about the role (#11543). Its sibling
    # ROLE_NOT_CATALOGUED_FOR_REVIEW carries the catalogue's answer. The PLAN
    # and IMPLEMENT members above still conflate the two; they belong to
    # #11541/#11542's vocabulary and are left for their owners, recorded in
    # PHASE_ROWS_STILL_CONFLATED above rather than only here.
    PlanRouteReason.PHASE_NOT_REVIEW: RejectionReason.OUTSIDE_CANARY_BOUND,
    PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_REVIEW: (
        RejectionReason.ROLE_PHASE_FORBIDDEN
    ),
    PlanRouteReason.LITERAL_FAMILY_UNSATISFIABLE: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
    # A hold, not a rejection: the tier table is the fixable thing and the
    # request was not inadmissible. Mapping it to the terminal code — which an
    # earlier draft did — put two holds for the same reason under opposite
    # receipt codes inside one module.
    PlanRouteReason.CAPABILITY_UNMAPPED: RejectionReason.ROUTE_UNAVAILABLE,
    PlanRouteReason.CONCRETE_MODEL_REQUESTED: (
        RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    ),
}


# --- how a spawn that never ran is classified ------------------------------
#
# Lifted here from ``plan_worker_runner`` by #11542 for the reason
# ``REFUSAL_CODES`` was: two actuators, one vocabulary. The copy that phase
# first made was not merely duplicated but *divergent* — hand-written string
# literals, two of which ("concrete-model-not-approved",
# "policy-forbids-principal") matched no ``DecisionReason`` member at all,
# while ``MODEL_NOT_ALLOWED`` and ``POLICY_CONFLICT`` were missing and would
# have been reported as retryable. #11657 had already hit exactly that and
# written the totality test; copying the idea rather than the code
# reintroduced it one module over. One definition makes that test cover both.
#: Routing-policy refusal reasons that mean *the request was inadmissible*
#: rather than *something operational is missing*. These map to
#: MODEL_REQUIREMENT_UNSATISFIABLE — retrying changes nothing, whatever an
#: operator edits; every other reason is ROUTE_UNAVAILABLE, where a caretaker
#: retry is right once whatever is missing is supplied. The remedy for a hold
#: may be a policy edit rather than a gateway one, so this does not say "look
#: at the gateway" — an earlier version did, and it was wrong for every hold
#: except an outage.
#:
#: Built from the resolver's own enum rather than from string literals, because
#: the first draft of this set contained a member that does not exist
#: (``concrete-model-not-allowed``) and omitted one that does
#: (``policy-conflict``) — a hand-written copy of another module's vocabulary
#: drifts silently and reads as a working classification while classifying
#: nothing. ``tests/test_plan_worker_runner.py`` requires every
#: :class:`DecisionReason` member to be classified, so a new one fails there
#: rather than defaulting to "retry it".
INADMISSIBLE_ROUTE_REASONS = frozenset(
    {
        DecisionReason.LITERAL_FAMILY_UNSATISFIABLE.value,
        DecisionReason.MODEL_NOT_ALLOWED.value,
        # Two policies claim the same rung: an operator must resolve it, and a
        # retry against an unresolved conflict is an infinite one.
        DecisionReason.POLICY_CONFLICT.value,
    }
)

#: Reasons deliberately left retryable, and why — so the judgement is visible
#: rather than implied by absence from the set above.
OPERATIONAL_ROUTE_REASONS = frozenset(
    {
        # The snapshot will be back; nothing about the request is wrong.
        DecisionReason.SNAPSHOT_UNAVAILABLE.value,
        # Unreachable on THIS seam, and the reason is worth stating because
        # an earlier comment here got it wrong: it is not that the resolver
        # never rejects on a hold — ``enforce_canary_route`` raises on every
        # non-SELECTED outcome, HELD included, which is the whole premise of
        # classifying on the reason. It is that a brokered child's model is
        # always a ``PLAN_TIER_CATALOG`` id, and ``requirement_for_model``
        # returns CAPABILITY only for an *empty* model string — so the resolver
        # cannot emit ``capability-unmapped`` for one of these spawns at all.
        # Classified anyway, because the table is required to be total.
        DecisionReason.CAPABILITY_UNMAPPED.value,
        # Collapses "no credential for this account" with "a provider lock
        # excluded every account". The first is operational and the second is
        # policy, and the resolver does not distinguish them here — so the
        # conservative reading is the retryable one, which sends the operator
        # to the gateway where both are visible.
        DecisionReason.NO_ELIGIBLE_ACCOUNT.value,
        # Reasons a *selected* decision carries. They reach a refusal only
        # through ``enforce_canary_route``'s empty-effective-model guard, which
        # a brokered child cannot trip (its legacy model is always the catalog
        # id) — so "not a refusal" is nearly but not exactly right, and
        # operational is the correct reading of the case that can occur.
        DecisionReason.MATCHED_POLICY.value,
        DecisionReason.NO_POLICY_APPLIES.value,
        # NOT one of those two, and an earlier comment here swept it in with
        # them: ``_legacy_decision`` emits it HELD, so it raises at the outcome
        # check rather than at the empty-model guard. It is unreachable for a
        # different reason — ``route_shadow.build_route_context`` always
        # constructs a ``LegacyRoute``, so ``context.legacy_route`` is never
        # ``None`` on this path. Operational either way: nothing about the
        # request is wrong.
        DecisionReason.NO_LEGACY_ROUTE.value,
    }
)


def refusal_for_spawn(spawn_out: dict[str, object]) -> RejectionReason:
    """Why a spawn that never ran did not run, in the receipt's vocabulary.

    The seam collapses a routing-policy refusal and a transport failure onto
    the same soft ``rc=-1``, so without the reason it left behind, both would
    be filed as ``ROUTE_UNAVAILABLE`` — which tells an operator the request was
    fine and to retry once whatever is missing is supplied. For an inadmissible
    route that is wrong: the retry will never succeed, and the thing to edit is
    the policy.
    """
    # Classified on the REASON alone, deliberately. A previous draft short-
    # circuited on ``refused_outcome == held`` first, reasoning that a hold is
    # retryable whatever its reason — and that silently reversed the one code
    # this canary is named after: ``RoutingAction.on_unavailable`` defaults to
    # HOLD, so the ordinary ``provider_lock=zai-harness`` refusal arrives as
    # HELD with ``literal-family-unsatisfiable``, and the guard turned it back
    # into a retryable ``ROUTE_UNAVAILABLE``. The reason is the durable fact
    # about the request; the outcome is a per-policy *dial* over what to do
    # when a lane is unavailable, and it is the wrong axis to classify on.
    reason = str(spawn_out.get("refused", "") or "")
    if reason in INADMISSIBLE_ROUTE_REASONS:
        return RejectionReason.MODEL_REQUIREMENT_UNSATISFIABLE
    return RejectionReason.ROUTE_UNAVAILABLE


@dataclass(frozen=True, slots=True)
class PlanRouteDecision:
    """One tier resolution, with everything needed to explain it afterwards."""

    decision_id: str
    outcome: PlanRouteOutcome
    rule: PlanRouteRule
    source: PlanRouteSource
    reason: PlanRouteReason
    catalog_revision: str
    route_policy_revision: str
    worker_role: str
    phase: str
    requirement_kind: str
    requirement_value: str
    served_model: str = ""
    """The concrete id a selected decision binds to. Empty on hold or reject —
    naming a plausible model for a worker that will not run is exactly the
    smuggling path ``WorkerReceipt``'s validator exists to close."""

    @property
    def selected(self) -> bool:
        return self.outcome is PlanRouteOutcome.SELECTED

    def explain(self) -> dict[str, object]:
        """The decision as a flat record, for receipts, logs and the operator."""
        return {
            "decision_id": self.decision_id,
            "outcome": self.outcome.value,
            "rule": self.rule.value,
            "source": self.source.value,
            "reason": self.reason.value,
            "catalog_revision": self.catalog_revision,
            "route_policy_revision": self.route_policy_revision,
            "worker_role": self.worker_role,
            "phase": self.phase,
            "requirement_kind": self.requirement_kind,
            "requirement_value": self.requirement_value,
            "served_model": self.served_model,
        }


def plan_roles_for_plan_phase() -> frozenset[WorkerRole]:
    """The catalogued roles legal at ``PLAN``: explorer, planner, architect.

    Derived from ``WORKER_CATALOG`` rather than listed, so the canary's menu and
    the admission rule table cannot disagree about what a Plan boundary may ask
    for. Two copies would drift the first time a role's ``allowed_phases``
    changed, and the drift would present as a refusal nobody could explain.
    """
    return frozenset(
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases
    )


def plan_canary_repo(config: HydraFlowConfig) -> str | None:
    """The one canonical repository the Plan canary is armed for, or ``None``."""
    raw = str(getattr(config, "fable_plan_canary_repo", "") or "")
    return canonicalize_repo(raw)


def plan_canary_armed(config: HydraFlowConfig) -> bool:
    """Whether the dial names a repository at all. The one-action switch.

    Read per boundary rather than captured at construction, so clearing the
    dial disarms on the **next** boundary with no restart. A live badge over a
    captured value is the lie ``settings_registry`` forbids, and an actuator an
    operator has to restart the factory to disarm is not a canary switch.
    """
    return plan_canary_repo(config) is not None


def plan_canary_covers(config: HydraFlowConfig, *, phase: DriverPhase | None) -> bool:
    """Whether this exact boundary is inside the canary's bound.

    All three clauses, and each is load-bearing in a different direction:

    1. the dial is armed at all — the off-switch;
    2. this repository's canonical identity is exactly the dialled one — the
       bound, and the reason a lossy slug can never match;
    3. the phase is ``PLAN`` — the reason implement, review and HITL stay
       Classic without a second guard anywhere else.
    """
    armed = plan_canary_repo(config)
    if armed is None:
        return False
    if phase is not CANARY_PHASE:
        return False
    return canonicalize_repo(str(getattr(config, "repo", "") or "")) == armed


def resolve_plan_model(
    request: WorkerDispatchRequest,
    *,
    phase: DriverPhase,
    route_policy_revision: str,
) -> PlanRouteDecision:
    """Resolve one Plan dispatch's model tier. The PLAN binding of the resolver.

    Kept as its own name because it is what ADR-0137's source-file citations
    and #11541's tests refer to; the body is
    :func:`resolve_worker_model` bound to the Plan canary's phase, role set and
    refusal vocabulary.
    """
    return resolve_worker_model(
        request,
        phase=phase,
        canary_phase=CANARY_PHASE,
        legal_roles=plan_roles_for_plan_phase(),
        phase_refusal=PlanRouteReason.PHASE_NOT_PLAN,
        role_refusal=PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_PLAN,
        route_policy_revision=route_policy_revision,
    )


def resolve_worker_model(
    request: WorkerDispatchRequest,
    *,
    phase: DriverPhase,
    canary_phase: DriverPhase,
    legal_roles: frozenset[WorkerRole],
    phase_refusal: PlanRouteReason,
    role_refusal: PlanRouteReason,
    route_policy_revision: str,
) -> PlanRouteDecision:
    """Resolve one dispatch's model tier. Pure, total, and first-match-wins.

    Total for the same reason ``routing_policy.explain`` is: it runs on a live
    dispatch path and an exception thrown here is a routing incident rather than
    a refusal an operator can read.

    **It deliberately does not ask which lane will serve the child.** An earlier
    draft took a ``lane_serves_anthropic`` argument and the caller answered it
    from ``repo_provider`` / ``planner_provider``, which was wrong in both
    directions: those dials are applied by ``repo_backend.apply_repo_provider``
    at the two *agentic* seams and never at the one-shot seam a brokered child
    takes, so a z.ai-pinned repository would have had every worker refused
    although its gateway lane serves Anthropic fine — and the lock that
    genuinely matters, a ``provider_lock=zai-harness`` routing policy, was never
    consulted at all.

    The honest division is: a brokered child is pinned to the gateway and the
    gateway derives the account from the model, so **no legacy dial can put one
    on GLM**. The only thing that can is a routing policy, and that refuses at
    ``route_enforcement.enforce_canary_route`` — before ``resolve_harness_env``,
    so with no credential in existence and zero upstream bytes. What remains
    here is the check this layer *can* answer: that the tier catalog's own
    answer satisfies the requirement it was resolved from.

    *canary_phase*, *legal_roles* and the two refusal reasons are parameters
    rather than constants because #11542 added a second bound over the **same**
    tier tables. Forking the resolver would have forked
    :data:`PLAN_TIER_CATALOG` with it, and two copies of "which id answers
    ``claude-opus``" is precisely the drift the table is code-owned to prevent —
    which is also why #11657's correction above lands on both canaries at once
    rather than needing to be found twice.
    """
    echo = _echo(request, phase, route_policy_revision)

    if phase is not canary_phase:
        return _refusal(echo, PlanRouteOutcome.REJECTED, phase_refusal)
    if request.worker_role not in legal_roles:
        return _refusal(echo, PlanRouteOutcome.REJECTED, role_refusal)

    requirement = request.model_requirement
    if requirement.kind is ModelRequirementKind.LITERAL_FAMILY:
        family, source, rule = (
            requirement.value,
            PlanRouteSource.DIRECTOR_LITERAL,
            PlanRouteRule.LITERAL_FAMILY_TO_CATALOGUED_ID,
        )
    elif requirement.kind is ModelRequirementKind.CAPABILITY:
        mapped = CAPABILITY_TIERS.get(requirement.value)
        if mapped is None or mapped not in LITERAL_FAMILIES:
            # ``mapped not in LITERAL_FAMILIES`` keeps this function TOTAL: the
            # family becomes a ``ModelRequirement`` below, whose validator
            # raises on an unknown value — and an exception on a live dispatch
            # path is a routing incident rather than a refusal an operator can
            # read.
            return _refusal(
                echo, PlanRouteOutcome.HELD, PlanRouteReason.CAPABILITY_UNMAPPED
            )
        family, source, rule = (
            mapped,
            PlanRouteSource.CAPABILITY_TABLE,
            PlanRouteRule.CAPABILITY_CLASS_TO_FAMILY,
        )
    else:
        return _refusal(
            echo, PlanRouteOutcome.REJECTED, PlanRouteReason.CONCRETE_MODEL_REQUESTED
        )

    # Checked against the FAMILY the table resolved to, never against the
    # incoming requirement. Two reasons, and the second was found by a test:
    # ``satisfied_by`` is the stronger predicate than ``has_anthropic_provenance``
    # (a catalog edit mapping ``claude-opus`` to a Sonnet id passes provenance
    # and would SELECT) — and on a CAPABILITY requirement ``satisfied_by``
    # returns True unconditionally, by design, so asking the requirement would
    # have left the capability arm with no fence at all and a table edit could
    # have answered ``high-reasoning`` with GLM.
    served = PLAN_TIER_CATALOG.get(family, "")
    if not _family_requirement(family).satisfied_by(served):
        return _refusal(
            echo,
            PlanRouteOutcome.REJECTED,
            PlanRouteReason.LITERAL_FAMILY_UNSATISFIABLE,
        )
    return _decision(
        echo,
        outcome=PlanRouteOutcome.SELECTED,
        rule=rule,
        source=source,
        reason=PlanRouteReason.NONE,
        served_model=served,
    )


class PlanCanaryLatch:
    """At most one issue holds the brokered-Plan slot for this repository.

    The issue's first acceptance criterion — *"initially one active
    Fable-directed issue per repository"* — as a fence rather than a convention.

    In-memory and per-run on purpose. A durable latch would survive the process
    that took it, so a crash mid-dispatch would leave the canary out of service
    until an operator noticed; a per-run latch is empty after a restart, which
    is also the true state (nothing is dispatching). The TTL covers the other
    direction: a hold abandoned *within* a run — an exception between claim and
    release — expires rather than wedging the canary for the process lifetime.

    ``ttl_seconds`` is **required**. It had a default, and the default came to
    equal the batch budget's ceiling — recreating the coincidence that makes the
    backstop able to reclaim a slot from a batch still running. A backstop whose
    value can silently drift into the thing it is a backstop *for* is not one,
    so there is nothing to drift: the composition root states it.
    """

    def __init__(self, *, ttl_seconds: int) -> None:
        self._ttl_seconds = ttl_seconds
        self._holder: int | None = None
        self._claimed_at: datetime | None = None

    @property
    def holder(self) -> int | None:
        """The issue currently holding the slot, if any."""
        return self._holder

    def claim(self, issue_number: int, *, now: datetime) -> bool:
        """Take the slot for *issue_number*, or report that someone else has it.

        Re-claiming is idempotent for the current holder: a driver reaching a
        second PLAN boundary for the same issue is the same logical Fable
        session, and refusing it would make the canary work exactly once per
        issue rather than once at a time.
        """
        held_by_another = self._holder is not None and self._holder != issue_number
        if held_by_another and not self._expired(now):
            return False
        self._holder = issue_number
        self._claimed_at = now
        return True

    def release(self, issue_number: int) -> None:
        """Free the slot, if *issue_number* is the one holding it."""
        if self._holder != issue_number:
            return
        self._holder = None
        self._claimed_at = None

    def _expired(self, now: datetime) -> bool:
        if self._claimed_at is None:
            return True
        return (now - self._claimed_at).total_seconds() > self._ttl_seconds


def _family_requirement(family: str) -> ModelRequirement:
    """The literal-family requirement a resolved tier must satisfy."""
    return ModelRequirement(kind=ModelRequirementKind.LITERAL_FAMILY, value=family)


def _echo(
    request: WorkerDispatchRequest, phase: DriverPhase, route_policy_revision: str
) -> dict[str, str]:
    return {
        "worker_role": request.worker_role.value,
        "phase": phase.value,
        "requirement_kind": request.model_requirement.kind.value,
        "requirement_value": request.model_requirement.value,
        "route_policy_revision": route_policy_revision,
    }


def _refusal(
    echo: dict[str, str], outcome: PlanRouteOutcome, reason: PlanRouteReason
) -> PlanRouteDecision:
    return _decision(
        echo,
        outcome=outcome,
        rule=PlanRouteRule.NONE_MATCHED,
        source=PlanRouteSource.NONE,
        reason=reason,
        served_model="",
    )


def _decision(
    echo: dict[str, str],
    *,
    outcome: PlanRouteOutcome,
    rule: PlanRouteRule,
    source: PlanRouteSource,
    reason: PlanRouteReason,
    served_model: str,
) -> PlanRouteDecision:
    identity = _decision_id(
        {
            **echo,
            "catalog_revision": PLAN_TIER_CATALOG_REVISION,
            "outcome": outcome.value,
            "rule": rule.value,
            "source": source.value,
            "reason": reason.value,
            "served_model": served_model,
        }
    )
    return PlanRouteDecision(
        decision_id=identity,
        outcome=outcome,
        rule=rule,
        source=source,
        reason=reason,
        catalog_revision=PLAN_TIER_CATALOG_REVISION,
        route_policy_revision=echo["route_policy_revision"],
        worker_role=echo["worker_role"],
        phase=echo["phase"],
        requirement_kind=echo["requirement_kind"],
        requirement_value=echo["requirement_value"],
        served_model=served_model,
    )


def _decision_id(fields: dict[str, object]) -> str:
    """Content-addressed, the same construction ``routing_policy`` uses.

    Deliberately the same shape rather than a fresh uuid: two components that
    resolve the same spawn derive the same id independently, which is what makes
    a receipt joinable to the decision that authorised it without either side
    having to carry the other's identifier.
    """
    payload = json.dumps(fields, sort_keys=True, separators=(",", ":"), default=str)
    return f"plan_{hashlib.sha256(payload.encode('utf-8')).hexdigest()[:32]}"
