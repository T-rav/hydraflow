"""Pure remediation classification (ADR-0100). No I/O; the loop performs the
side effects. Ambiguity ('the decision moved') is reached by recurrence, not
guessed: FAIL files an issue until attempts hit the budget, then escalates.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel

from adr_conformance import AdrConformance, CheckOutcome


class RemediationAction(StrEnum):
    NONE = "none"
    REPOINT = "repoint"
    FILE_ISSUE = "file_issue"
    ESCALATE = "escalate"


class RemediationDecision(BaseModel):
    action: RemediationAction
    reason: str = ""


def classify_remediation_over(
    *,
    adr_id: str,
    outcome: CheckOutcome,
    rename_match: str | None,
    attempts: int,
    max_attempts: int = 3,
) -> RemediationDecision:
    """The classification itself, over primitives rather than an object.

    Split out for #11749 so ``policy.python_engine`` can reach the SAME
    decision function from a ``Fact`` sequence instead of re-deriving it from a
    reconstructed ``AdrConformance``. One definition, two shapes of caller —
    the loop's behaviour through the decision seam is byte-for-byte what it was
    when it called ``classify_remediation`` directly.
    """
    if outcome in (CheckOutcome.PASS, CheckOutcome.MANUAL, CheckOutcome.SKIPPED):
        return RemediationDecision(action=RemediationAction.NONE)
    if outcome is CheckOutcome.UNRESOLVED and rename_match:
        return RemediationDecision(
            action=RemediationAction.REPOINT, reason=f"check renamed to {rename_match}"
        )
    # UNRESOLVED-without-match and FAIL share the code-drift path.
    if attempts >= max_attempts:
        return RemediationDecision(
            action=RemediationAction.ESCALATE,
            reason=f"unresolved after {attempts} attempts; decision may be stale",
        )
    return RemediationDecision(
        action=RemediationAction.FILE_ISSUE,
        reason=f"conformance {outcome} for {adr_id}",
    )


def classify_remediation(
    conf: AdrConformance,
    *,
    rename_match: str | None,
    attempts: int,
    max_attempts: int = 3,
) -> RemediationDecision:
    """Object-shaped adapter over :func:`classify_remediation_over`."""
    return classify_remediation_over(
        adr_id=conf.adr_id,
        outcome=conf.outcome,
        rename_match=rename_match,
        attempts=attempts,
        max_attempts=max_attempts,
    )
