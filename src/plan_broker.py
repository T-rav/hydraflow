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
    WorkerRole,
)
from hydraflow_gateway.routing_policy import canonicalize_repo

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
    """
    echo = _echo(request, phase, route_policy_revision)

    if phase is not CANARY_PHASE:
        return _refusal(echo, PlanRouteOutcome.REJECTED, PlanRouteReason.PHASE_NOT_PLAN)
    if request.worker_role not in plan_roles_for_plan_phase():
        return _refusal(
            echo,
            PlanRouteOutcome.REJECTED,
            PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_PLAN,
        )

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
