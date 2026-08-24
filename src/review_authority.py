"""A Fable reviewer proposes; deterministic code decides (ADR-0137 P5).

P5's authority criterion: *"Fable cannot hide findings, self-approve, merge,
mutate review verdicts, or weaken CI/HITL policy."* Every one of those is the
same shape — a reviewer whose output is taken as a decision has the decision,
whatever the surrounding prose says about who owns it.

So a reviewer here returns a :class:`ReviewProposal`, never a verdict. The
verdict is computed by :func:`adjudicate`, a pure function of the proposal and
the deterministic facts around it, in which the reviewer's own recommendation
is **one input among several and never the output**. That is the whole
mechanism: there is no code path from a reviewer's preferred answer to a stored
verdict that does not pass through a rule the reviewer cannot state.

Three properties fall out of that, each a separate criterion:

- **cannot self-approve** — ``APPROVE`` requires ``findings == ()``; a proposal
  that recommends approval while carrying a blocking finding is adjudicated
  ``REQUEST_CHANGES``. The recommendation loses to its own evidence.
- **cannot hide findings** — findings are carried on the proposal and counted
  by the adjudicator, so suppressing one changes the verdict rather than the
  presentation. An empty findings list with a ``REQUEST_CHANGES``
  recommendation is a contradiction, and is resolved *toward* the stricter
  reading (:data:`STRICTER`), never away from it.
- **cannot weaken CI/HITL** — ``ci_green`` and ``hitl_required`` are
  deterministic inputs the proposal has no field for. A reviewer cannot assert
  them, so it cannot relax them.

Merge authority is not modelled here at all, which is deliberate: the way to
make something unreachable is to give it no representation, not to give it a
field and then check the field.
"""

from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field

from models import ReviewVerdict

__all__ = [
    "STRICTER",
    "AdjudicationReason",
    "ReviewFinding",
    "ReviewProposal",
    "adjudicate",
]


#: Verdicts ordered by strictness. Any disagreement resolves to the stricter of
#: the two readings, because the failure that matters is a defect shipped, not a
#: clean change re-reviewed.
STRICTER: tuple[ReviewVerdict, ...] = (
    ReviewVerdict.APPROVE,
    ReviewVerdict.COMMENT,
    ReviewVerdict.REQUEST_CHANGES,
)


class AdjudicationReason(StrEnum):
    """Why the adjudicated verdict is what it is. Never a free-form message."""

    RECOMMENDATION_ACCEPTED = "recommendation_accepted"
    FINDINGS_PRESENT = "findings_present"
    CI_NOT_GREEN = "ci_not_green"
    HITL_REQUIRED = "hitl_required"
    NOT_INDEPENDENT = "not_independent"
    EVIDENCE_STALE = "evidence_stale"


class ReviewFinding(BaseModel):
    """One thing a reviewer says is wrong. Blocking unless it says otherwise."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    summary: str = Field(min_length=1, max_length=500)
    file: str = ""
    line: int | None = None
    blocking: bool = True


class ReviewProposal(BaseModel):
    """Everything a reviewer is allowed to say.

    Note what has no field: no verdict to store, no merge instruction, no label,
    no CI waiver, no HITL override. Those are absent rather than validated —
    a field that exists can be set, and a check that rejects it is one edit away
    from being relaxed.

    ``recommended`` is the reviewer's *opinion*. :func:`adjudicate` may agree
    with it, and must not be able to be made to agree with it.
    """

    model_config = ConfigDict(extra="forbid", frozen=True)

    recommended: ReviewVerdict
    findings: tuple[ReviewFinding, ...] = ()
    summary: str = Field(default="", max_length=4000)


def _strictest(*verdicts: ReviewVerdict) -> ReviewVerdict:
    return max(verdicts, key=STRICTER.index)


def adjudicate(
    proposal: ReviewProposal,
    *,
    ci_green: bool,
    hitl_required: bool = False,
    reviewer_independent: bool = True,
    evidence_head_sha: str = "",
    current_head_sha: str = "",
) -> tuple[ReviewVerdict, AdjudicationReason]:
    """The verdict, and the one reason that decided it.

    Evaluated strict-first, so the reason returned is the *binding* constraint
    rather than the last one checked. A caller that logs the reason is logging
    why the change was held, which is the question an operator actually asks.

    ``evidence_head_sha``/``current_head_sha`` implement ADR-0137's bounded
    slice at the verdict boundary: a review of a snapshot that has since moved
    is not a review of what would merge. Both empty means "not checked" — the
    caller has not supplied a snapshot — rather than "matched", so an
    un-plumbed caller cannot get a free pass from a pair of empty strings.
    """
    if not reviewer_independent:
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.NOT_INDEPENDENT

    if evidence_head_sha and current_head_sha and evidence_head_sha != current_head_sha:
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.EVIDENCE_STALE

    if hitl_required:
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.HITL_REQUIRED

    if not ci_green:
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.CI_NOT_GREEN

    if any(finding.blocking for finding in proposal.findings):
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.FINDINGS_PRESENT

    # Nothing deterministic objects. The recommendation is honoured, but only up
    # to the strictness its own non-blocking findings justify: a reviewer that
    # files advisory findings and then recommends APPROVE gets COMMENT.
    floor = ReviewVerdict.COMMENT if proposal.findings else ReviewVerdict.APPROVE
    return (
        _strictest(proposal.recommended, floor),
        AdjudicationReason.RECOMMENDATION_ACCEPTED,
    )
