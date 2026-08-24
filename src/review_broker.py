"""Admission for the Fable REVIEW canary (ADR-0137 P5).

The third dial, deliberately not a widening of the first two. "Widen one role
boundary at a time" is the epic's own rollout rule, and one dial covering plan,
implement and review would mean an operator running the Plan canary today woke
up dispatching *reviewers* tomorrow. Three dials keep three decisions separate,
and keep #11541's and #11542's bounds literally true while this one is empty.

Review is the boundary where the independence rules actually bind, so admission
here carries one clause the other two brokers do not: a judge must not be the
implementer. That fence already exists in ``driver_contracts`` on the requesting
spawn id; what this module adds is the *canary* gate around it, so an unarmed
repository dispatches no reviewer at all and the fence is never the only thing
standing between an implementer and its own review.

Two of this module's rules were rewritten in review (#11543), both because they
were green while guarding nothing:

- the menu excludes write-scoped roles. Derived from phase alone it included
  ``DEBUGGER``, so arming a dial that reads as a read-only *reviewer* canary
  also armed a writer at REVIEW — with the implement dial still empty;
- an absent ``requesting_spawn_id`` refuses rather than admits. Nothing writes
  that field in ``src/``, so admitting it meant the fence could only ever refuse
  a request in which the fenced party volunteered the value that refused it.

Pure: no I/O, no clock, no spawn. Every function is a decision about a
configuration and a request.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from driver_contracts import (
    WORKER_CATALOG,
    DriverPhase,
    RejectionReason,
    WorkerRole,
    WriteScope,
)
from hydraflow_gateway.routing_policy import canonicalize_repo
from plan_broker import PlanRouteReason, resolve_worker_model

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from config import HydraFlowConfig
    from driver_contracts import WorkerDispatchRequest
    from plan_broker import PlanRouteDecision

__all__ = [
    "CANARY_PHASE",
    "resolve_review_model",
    "review_canary_armed",
    "review_canary_covers",
    "review_canary_repo",
    "review_roles_for_review_phase",
    "reviewer_independence_refusal",
]

CANARY_PHASE = DriverPhase.REVIEW
"""The one phase this canary may dispatch into."""


def review_roles_for_review_phase() -> frozenset[WorkerRole]:
    """The Review canary's menu: catalogued roles legal at ``REVIEW`` that write nothing.

    Two clauses, and the second is the one that took a defect to learn.

    Derived from ``WORKER_CATALOG`` rather than hardcoded, for the same reason
    the plan and implement brokers derive theirs: the canary's menu and the
    admission rule table must not be able to disagree about what a REVIEW
    boundary may ask for, and a hardcoded list is a second description of the
    catalogue, free to drift from it silently.

    Filtered to ``WriteScope.NONE`` because the catalogue also legalises
    ``DEBUGGER`` at ``REVIEW``, and a debugger holds ``ISSUE_WORKTREE``. Without
    the filter, an operator arming what the dial calls a *reviewer* canary also
    armed a **writer** at REVIEW — without arming ``fable_implement_canary_repo``,
    which is the dial that exists to make widening the write boundary its own
    decision. "Widen one role boundary at a time" is the epic's rollout rule and
    the entire reason there are three dials; a menu that smuggles a writer in
    behind a read-only name breaks it while every dial still reads as unarmed.

    A debugger at REVIEW is not forbidden — it is simply not this dial's to
    arm. The dial that widens the write boundary is the one that must be turned.
    """
    return frozenset(
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases and entry.write_scope is WriteScope.NONE
    )


def review_canary_repo(config: HydraFlowConfig) -> str | None:
    """The one canonical repository the Review canary is armed for, or ``None``."""
    raw = str(getattr(config, "fable_review_canary_repo", "") or "")
    return canonicalize_repo(raw)


def review_canary_armed(config: HydraFlowConfig) -> bool:
    """Whether the dial names a repository at all. The one-action switch.

    Read per boundary rather than captured at construction, so clearing the dial
    disarms on the **next** boundary with no restart. A canary switch an
    operator has to restart the factory to use is not a canary switch, and a
    live badge over a captured value is the lie ``settings_registry`` forbids.
    """
    return review_canary_repo(config) is not None


def review_canary_covers(config: HydraFlowConfig, *, phase: DriverPhase | None) -> bool:
    """Whether this exact boundary is inside the Review canary's bound.

    Three clauses, each load-bearing in a different direction:

    1. the dial is armed at all — the off-switch, and the reason an operator who
       armed only the Plan canary dispatches no reviewers;
    2. this repository's canonical identity is exactly the dialled one — the
       bound, and the reason a lossy slug can never match;
    3. the phase is ``REVIEW`` — the reason plan, implement and HITL are
       unaffected by arming this one.
    """
    armed = review_canary_repo(config)
    if armed is None:
        return False
    if phase is not CANARY_PHASE:
        return False
    return canonicalize_repo(str(getattr(config, "repo", "") or "")) == armed


def resolve_review_model(
    request: WorkerDispatchRequest,
    *,
    phase: DriverPhase,
    route_policy_revision: str,
) -> PlanRouteDecision:
    """Resolve one REVIEW dispatch's model tier.

    The REVIEW binding of ``plan_broker.resolve_worker_model``: the same
    code-owned tier tables, the same content-addressed decision record, the
    same "a literal family resolves literally or refuses", over this phase's
    role set and refusal vocabulary. A third copy of the resolver would carry a
    third answer to "which id is ``claude-opus``" — and this is the phase where
    that answer matters most, because the catalogued reviewer asks for Opus by
    name and a canary that quietly reviewed with Sonnet would still look armed.

    Imported at module scope, matching ``implement_broker``'s precedent rather
    than deferring: ``plan_broker`` is a peer pure broker that imports nothing
    from here, so there is no cycle to avoid and a function-local import would
    be a smell justified by a hazard that does not exist.
    """
    return resolve_worker_model(
        request,
        phase=phase,
        canary_phase=CANARY_PHASE,
        legal_roles=review_roles_for_review_phase(),
        phase_refusal=PlanRouteReason.PHASE_NOT_REVIEW,
        role_refusal=PlanRouteReason.ROLE_NOT_CATALOGUED_FOR_REVIEW,
        route_policy_revision=route_policy_revision,
    )


def reviewer_independence_refusal(
    *,
    role: WorkerRole,
    requesting_spawn_id: str | None,
    implementer_spawn_ids: Iterable[str],
) -> RejectionReason | None:
    """``SELF_REVIEW_FORBIDDEN`` when this request would review its own work.

    The catalogue decides which roles must be independent
    (``independent_of_implementer``), not this function — a role list here would
    be a second description of the catalogue and would go stale the day a role
    is added, which is the failure class #11673 swept.

    Keyed on the requesting **spawn** id, matching ``driver_contracts``: a
    ``request_id`` is minted fresh per request and could never collide with a
    spawn id, so keying on it would leave this fence permanently unreachable —
    green, and guarding nothing.

    An **absent** requesting spawn is ``LINEAGE_UNKNOWN``, not admission. The
    first draft of this function read it the other way — no parent spawn means a
    fresh process by definition — and wrote that down as "the intended reading,
    not an oversight". It was an oversight, and documenting it made it worse:
    nothing in ``src/`` writes ``requesting_spawn_id``, so the only producer is
    the director model's own JSON, and the only request this fence could ever
    refuse was one where the party being fenced volunteered the value that got
    its own request refused. The fence was unreachable, a test pinned the
    unreachability as correct, and the next reader stops looking — the exact
    shape of #11670's guard that was never added and the T29 veto that sat inert
    for 104 days.

    Independence is a claim about provenance. A request that cannot state its
    provenance has not made the claim, so it is refused rather than believed.
    The refusal is a *separate* code from ``SELF_REVIEW_FORBIDDEN`` because the
    two say different things to an operator: one is a caller that failed to
    stamp lineage, the other is a worker caught grading its own homework.
    """
    entry = WORKER_CATALOG.get(role)
    if entry is None or not entry.independent_of_implementer:
        return None
    if not (requesting_spawn_id or "").strip():
        return RejectionReason.LINEAGE_UNKNOWN
    if requesting_spawn_id in set(implementer_spawn_ids):
        return RejectionReason.SELF_REVIEW_FORBIDDEN
    return None
