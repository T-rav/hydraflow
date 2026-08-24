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
    SNAPSHOT_UNKNOWN = "snapshot_unknown"
    """Exactly one side of the head-sha pair was supplied.

    A partial pair is a *broken caller* — a head-sha lookup that failed and
    passed an empty string on — not an un-plumbed one. Reading it as "no
    comparison, therefore no objection" is how a failed lookup silently
    disables the bounded-slice rule at the one boundary it exists to hold.
    """


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


def _snapshot_objection(
    evidence_head_sha: str, current_head_sha: str
) -> AdjudicationReason | None:
    """The bounded-slice rule read over a head-sha pair, in three states.

    One function rather than two conditions at the call site, because the two
    live states are not independent: which one applies is decided by *how much*
    of the pair arrived, and splitting that decision is how the partial case
    ended up filed under "not checked".
    """
    if evidence_head_sha and current_head_sha:
        if evidence_head_sha == current_head_sha:
            return None
        return AdjudicationReason.EVIDENCE_STALE
    if evidence_head_sha or current_head_sha:
        return AdjudicationReason.SNAPSHOT_UNKNOWN
    return None


def adjudicate(
    proposal: ReviewProposal,
    *,
    ci_green: bool,
    hitl_required: bool,
    reviewer_independent: bool,
    evidence_head_sha: str = "",
    current_head_sha: str = "",
) -> tuple[ReviewVerdict, AdjudicationReason]:
    """The verdict, and the one reason that decided it.

    Evaluated strict-first, so the reason returned is the *binding* constraint
    rather than the last one checked. A caller that logs the reason is logging
    why the change was held, which is the question an operator actually asks.

    ``hitl_required`` and ``reviewer_independent`` are required keyword
    arguments with no defaults, for ``admit_dispatch``'s stated reason about the
    same class of input: *a caller that forgets either must fail loudly rather
    than dispatch fail-open.* They defaulted to ``False``/``True`` — the
    permissive reading of both — which meant the one caller most likely to exist
    (wiring written in a hurry, against a fence whose other half had already
    been found unreachable) got a verdict computed as though no human was
    needed and the reviewer was known to be independent. A ``TypeError`` at the
    call site is the cheapest possible version of that bug.

    ``evidence_head_sha``/``current_head_sha`` implement ADR-0137's bounded
    slice at the verdict boundary: a review of a snapshot that has since moved
    is not a review of what would merge. The pair is read in three states, not
    two:

    - **both supplied** — compared; a mismatch is ``EVIDENCE_STALE``.
    - **exactly one supplied** — ``SNAPSHOT_UNKNOWN``, and it blocks. A caller
      that has one side has plumbed the check; an empty other side is a lookup
      that failed, and treating a failed lookup as "no objection" turns the
      bounded-slice rule off exactly when the repository state is unknown.
    - **neither supplied** — not checked, and it does not block. This is a real
      gap rather than a property: the verdict is indistinguishable from a
      matched pair, and the honest statement is that a caller which plumbs
      neither side simply does not get the bounded slice. An earlier docstring
      claimed the two were distinguishable; they are byte-identical, so the
      claim pinned nothing and a test written against it could not fail. The
      remedy is a caller that plumbs both, which the partial-pair rule above
      now makes the only halfway state worth writing.
    """
    if not reviewer_independent:
        return ReviewVerdict.REQUEST_CHANGES, AdjudicationReason.NOT_INDEPENDENT

    snapshot = _snapshot_objection(evidence_head_sha, current_head_sha)
    if snapshot is not None:
        return ReviewVerdict.REQUEST_CHANGES, snapshot

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
    verdict = _strictest(proposal.recommended, floor)
    # The reason names the BINDING constraint here too. When the advisory floor
    # lifts the verdict above what was recommended, the recommendation was not
    # accepted — it lost to the reviewer's own findings, which is what
    # FINDINGS_PRESENT already says. Reporting RECOMMENDATION_ACCEPTED for an
    # APPROVE that came back COMMENT was a reason code that contradicted its own
    # verdict, in the one field an operator reads to learn why.
    reason = (
        AdjudicationReason.FINDINGS_PRESENT
        if verdict is not proposal.recommended
        else AdjudicationReason.RECOMMENDATION_ACCEPTED
    )
    return verdict, reason
