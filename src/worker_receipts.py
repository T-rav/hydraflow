"""The receipt-shaped helpers every brokered worker actuator needs (#11543).

Three functions, each already written twice — once in :mod:`plan_worker_runner`
(#11541) and again, byte for byte, in :mod:`implement_worker_runner` (#11542) —
and about to be written a third time for the REVIEW canary. Lifted here for the
reason ``plan_broker.REFUSAL_CODES`` and ``plan_broker.refusal_for_spawn`` were
lifted out of the Plan actuator by #11542: N actuators over one vocabulary
drift, each copy stays locally plausible while it does, and the divergence is
only visible to a reader holding both files open. #11670 paid for that lesson
with a refusal table whose copy had two invented members and two missing ones.

What is deliberately **not** here: ``_refusal`` and ``_child_lineage``. Those
two already differ between the Plan and Implement actuators — the Implement
copy takes no ``lineage`` argument, so its post-spawn refusals drop the spawn
id that #11657 added the argument to preserve. Unifying them would change a
shipped canary's receipts, which is a decision for the phase that owns that
behaviour rather than a side effect of adding a third actuator.

Pure: no I/O beyond the pricing table's own lazy load, no clock, no spawn.

Decision path, no authority. It may not spawn a process, mutate a label or
write convergence state -- pinned by
``tests/architecture/test_director_no_authority.py``, which requires this
sentence and this module's ``DECISION_PATH_MODULES`` entry to travel together
in both directions.
"""

from __future__ import annotations

import hashlib

from plan_broker import (
    PLAN_TIER_CATALOG_REVISION,
    PlanRouteDecision,
    PlanRouteOutcome,
    PlanRouteReason,
    PlanRouteRule,
    PlanRouteSource,
)

__all__ = [
    "artifact_digest",
    "estimate_worker_cost",
    "unresolved_decision",
]


def artifact_digest(text: str) -> str:
    """The content address of one child's retained output.

    The **whole** digest. This read ``hexdigest()[:64]`` until #11718 — a slice
    of a 64-character hexdigest to 64 characters, so a bound that bounded
    nothing while reading like a deliberate truncation. Dropping it changes no
    address the factory has ever minted. The real bound is
    ``WorkerReceipt.artifact_digest``'s 128-character field, which ``sha256:``
    plus 64 hex characters fits with room to spare, and which fails loudly
    rather than silently shortening a content address.
    """
    return f"sha256:{hashlib.sha256(text.encode('utf-8')).hexdigest()}"


def estimate_worker_cost(model: str, usage: object) -> float:
    """One child's spend, from the token counts the seam actually reported.

    Zero when the backend reported none, and zero for an unpriced model — never
    a guess dressed as a measurement. ADR-0137 B5's bar reads *"100% of accepted
    workers carry lineage, cost and effective-route receipts"*, and a fabricated
    cost would satisfy its letter while destroying it.
    """
    if not isinstance(usage, dict):
        return 0.0
    from model_pricing import load_pricing

    cost = load_pricing().estimate_cost(
        model,
        int(usage.get("input_tokens", 0) or 0),
        int(usage.get("output_tokens", 0) or 0),
        int(usage.get("cache_creation_input_tokens", 0) or 0),
        int(usage.get("cache_read_input_tokens", 0) or 0),
    )
    return round(cost, 6) if cost else 0.0


def unresolved_decision(route_policy_revision: str) -> PlanRouteDecision:
    """A decision record for a refusal taken before any tier was resolved.

    It carries the route-policy revision because a receipt joins on that, and
    nothing else: inventing a rule, a source or a served model for a resolution
    that never ran would put fiction into the one record a canary's evidence is
    read from.
    """
    return PlanRouteDecision(
        decision_id="",
        outcome=PlanRouteOutcome.REJECTED,
        rule=PlanRouteRule.NONE_MATCHED,
        source=PlanRouteSource.NONE,
        reason=PlanRouteReason.NONE,
        catalog_revision=PLAN_TIER_CATALOG_REVISION,
        route_policy_revision=route_policy_revision,
        worker_role="",
        phase="",
        requirement_kind="",
        requirement_value="",
    )
