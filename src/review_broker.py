"""Admission for the Fable REVIEW canary (ADR-0137 P5).

The third dial, deliberately not a widening of the first two. "Widen one role
boundary at a time" is the epic's own rollout rule, and one dial covering plan,
implement and review would mean an operator running the Plan canary today woke
up dispatching *reviewers* tomorrow. Three dials keep three decisions separate,
and keep #11541's and #11542's bounds literally true while this one is empty.

Review is the boundary where the independence rules actually bind, so admission
here carries one clause the other two brokers do not: a reviewer must not be the
implementer. That fence already exists in ``driver_contracts`` on the requesting
spawn id; what this module adds is the *canary* gate around it, so an unarmed
repository dispatches no reviewer at all and the fence is never the only thing
standing between an implementer and its own review.

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
)
from hydraflow_gateway.routing_policy import canonicalize_repo

if TYPE_CHECKING:  # pragma: no cover - typing only
    from collections.abc import Iterable

    from config import HydraFlowConfig

__all__ = [
    "CANARY_PHASE",
    "review_canary_armed",
    "review_canary_covers",
    "review_canary_repo",
    "review_roles_for_review_phase",
    "reviewer_independence_refusal",
]

CANARY_PHASE = DriverPhase.REVIEW
"""The one phase this canary may dispatch into."""


def review_roles_for_review_phase() -> frozenset[WorkerRole]:
    """The catalogued roles legal at ``REVIEW``.

    Derived from ``WORKER_CATALOG`` for the same reason the plan and implement
    brokers derive theirs: the canary's menu and the admission rule table must
    not be able to disagree about what a REVIEW boundary may ask for. A
    hardcoded pair here would be a second description of the catalogue, free to
    drift from it silently.
    """
    return frozenset(
        role
        for role, entry in WORKER_CATALOG.items()
        if CANARY_PHASE in entry.allowed_phases
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

    ``None`` requesting spawn means the request has no parent spawn to compare,
    which is a *fresh* process by definition and therefore admissible. That is
    the intended reading, not an oversight: the fence exists to catch an
    implementer asking to review itself, and a request with no implementer
    lineage is not that.
    """
    entry = WORKER_CATALOG.get(role)
    if entry is None or not entry.independent_of_implementer:
        return None
    if requesting_spawn_id is None:
        return None
    if requesting_spawn_id in set(implementer_spawn_ids):
        return RejectionReason.SELF_REVIEW_FORBIDDEN
    return None
