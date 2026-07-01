"""Pure remediation classification (ADR-0098). No I/O; the loop performs the
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


def classify_remediation(
    conf: AdrConformance,
    *,
    rename_match: str | None,
    attempts: int,
    max_attempts: int = 3,
) -> RemediationDecision:
    if conf.outcome in (CheckOutcome.PASS, CheckOutcome.MANUAL, CheckOutcome.SKIPPED):
        return RemediationDecision(action=RemediationAction.NONE)
    if conf.outcome is CheckOutcome.UNRESOLVED and rename_match:
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
        reason=f"conformance {conf.outcome} for {conf.adr_id}",
    )
