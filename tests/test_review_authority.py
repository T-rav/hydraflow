"""A Fable reviewer proposes; deterministic code decides (ADR-0137 P5)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from models import ReviewVerdict
from review_authority import (
    STRICTER,
    AdjudicationReason,
    ReviewFinding,
    ReviewProposal,
    adjudicate,
)

#: The deterministic facts, all in their *permissive* state, spread at every
#: call site. :func:`adjudicate` no longer defaults ``hitl_required`` or
#: ``reviewer_independent``: a caller that forgets either must fail loudly
#: rather than adjudicate fail-open, which is the rule ``admit_dispatch``
#: already states for the same class of input. A fixture here rather than a
#: default there, so the *test* carries the permissive reading and production
#: wiring cannot inherit it by omission.
_DETERMINISTIC: dict[str, bool] = {
    "ci_green": True,
    "hitl_required": False,
    "reviewer_independent": True,
}

_CLEAN = ReviewProposal(recommended=ReviewVerdict.APPROVE)
_BLOCKING = ReviewProposal(
    recommended=ReviewVerdict.APPROVE,
    findings=(ReviewFinding(summary="null deref on the empty path"),),
)


def test_a_clean_proposal_with_green_ci_is_approved() -> None:
    verdict, reason = adjudicate(_CLEAN, **_DETERMINISTIC)
    assert verdict is ReviewVerdict.APPROVE
    assert reason is AdjudicationReason.RECOMMENDATION_ACCEPTED


def test_a_reviewer_cannot_self_approve_over_its_own_blocking_finding() -> None:
    verdict, reason = adjudicate(_BLOCKING, **_DETERMINISTIC)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.FINDINGS_PRESENT


def test_advisory_findings_cap_an_approval_at_comment() -> None:
    proposal = ReviewProposal(
        recommended=ReviewVerdict.APPROVE,
        findings=(ReviewFinding(summary="nit: naming", blocking=False),),
    )
    verdict, reason = adjudicate(proposal, **_DETERMINISTIC)
    assert verdict is ReviewVerdict.COMMENT
    # The reason must name the constraint that actually bound. APPROVE came
    # back COMMENT, so the recommendation was NOT accepted — reporting
    # RECOMMENDATION_ACCEPTED there is a reason code contradicting its own
    # verdict, in the field an operator reads to learn why (#11543). The
    # earlier test discarded the reason, so nothing pinned it.
    assert reason is AdjudicationReason.FINDINGS_PRESENT


def test_an_honoured_recommendation_still_says_so_when_findings_are_advisory() -> None:
    """The other half: FINDINGS_PRESENT must not swallow every advisory case.

    A reviewer that files a nit and recommends COMMENT got exactly what it
    asked for; the findings changed nothing, so the binding constraint is the
    recommendation. Without this, reporting FINDINGS_PRESENT unconditionally
    whenever ``findings`` is non-empty would pass the test above.
    """
    proposal = ReviewProposal(
        recommended=ReviewVerdict.COMMENT,
        findings=(ReviewFinding(summary="nit: naming", blocking=False),),
    )
    verdict, reason = adjudicate(proposal, **_DETERMINISTIC)
    assert verdict is ReviewVerdict.COMMENT
    assert reason is AdjudicationReason.RECOMMENDATION_ACCEPTED


def test_a_reviewer_cannot_approve_past_red_ci() -> None:
    verdict, reason = adjudicate(_CLEAN, **_DETERMINISTIC | {"ci_green": False})
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.CI_NOT_GREEN


def test_a_reviewer_cannot_approve_past_a_hitl_requirement() -> None:
    verdict, reason = adjudicate(_CLEAN, **_DETERMINISTIC | {"hitl_required": True})
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.HITL_REQUIRED


def test_a_non_independent_reviewer_cannot_approve() -> None:
    verdict, reason = adjudicate(
        _CLEAN, **_DETERMINISTIC | {"reviewer_independent": False}
    )
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.NOT_INDEPENDENT


def test_a_review_of_a_moved_snapshot_is_not_a_review_of_what_would_merge() -> None:
    verdict, reason = adjudicate(
        _CLEAN, **_DETERMINISTIC, evidence_head_sha="a" * 40, current_head_sha="b" * 40
    )
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.EVIDENCE_STALE


def test_a_matching_snapshot_does_not_block() -> None:
    verdict, _ = adjudicate(
        _CLEAN, **_DETERMINISTIC, evidence_head_sha="a" * 40, current_head_sha="a" * 40
    )
    assert verdict is ReviewVerdict.APPROVE


@pytest.mark.parametrize(
    "supplied",
    [{"evidence_head_sha": "a" * 40}, {"current_head_sha": "a" * 40}],
    ids=["evidence-side-only", "current-side-only"],
)
def test_half_a_snapshot_pair_blocks_instead_of_approving(
    supplied: dict[str, str],
) -> None:
    """A partial pair is a BROKEN caller, not an un-plumbed one (#11543).

    This replaces ``test_an_unplumbed_snapshot_pair_is_not_treated_as_a_match``,
    which asserted ``verdict is APPROVE`` for the both-empty case — the same
    output "treated as a match" produces, so it could not fail for the reason
    it named. Its second half asserted that one supplied side must *not* block,
    which pinned the live risk as correct: a caller whose head-sha lookup just
    failed passes ``current_head_sha=""`` and silently switches ADR-0137's
    bounded-slice rule off at the one boundary it holds.
    """
    verdict, reason = adjudicate(_CLEAN, **_DETERMINISTIC, **supplied)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.SNAPSHOT_UNKNOWN


def test_a_caller_that_plumbs_neither_side_does_not_get_the_bounded_slice() -> None:
    """The honest statement of the gap, not a property dressed as one.

    Both empty and both matching produce the same verdict and the same reason —
    they are indistinguishable by construction, so no test can separate them
    and none should claim to. What IS observable, and what this pins, is that
    the un-plumbed reading applies to the empty pair ONLY: the halfway state
    now blocks, so the only way to reach a verdict without the bounded slice is
    to have plumbed no part of it at all.
    """
    verdict, reason = adjudicate(_CLEAN, **_DETERMINISTIC)
    assert (verdict, reason) == (
        ReviewVerdict.APPROVE,
        AdjudicationReason.RECOMMENDATION_ACCEPTED,
    )


def test_a_reviewer_cannot_downgrade_a_deterministic_block() -> None:
    """The recommendation loses to every deterministic constraint, not just some."""
    for override in (
        {"ci_green": False},
        {"hitl_required": True},
        {"reviewer_independent": False},
    ):
        verdict, _ = adjudicate(
            ReviewProposal(recommended=ReviewVerdict.APPROVE),
            **_DETERMINISTIC | override,
        )
        assert verdict is ReviewVerdict.REQUEST_CHANGES, override


def test_a_forgetful_caller_fails_loudly_rather_than_adjudicating_fail_open() -> None:
    """``hitl_required`` and ``reviewer_independent`` carry no defaults (#11543).

    They defaulted to the permissive reading of both, so wiring that forgot
    them got a verdict computed as though no human was needed and the reviewer
    was known independent — against a fence whose other half had already been
    found unreachable. ``admit_dispatch`` states the rule for this exact class
    of input; this is the same rule, at the verdict boundary.
    """
    for omitted in ("hitl_required", "reviewer_independent"):
        kwargs = {k: v for k, v in _DETERMINISTIC.items() if k != omitted}
        with pytest.raises(TypeError, match=omitted):
            adjudicate(_CLEAN, **kwargs)  # type: ignore[arg-type]


def test_the_binding_constraint_is_the_reason_reported() -> None:
    """Strict-first, so the reason is why it was held, not the last check run."""
    _, reason = adjudicate(
        _BLOCKING,
        ci_green=False,
        hitl_required=True,
        reviewer_independent=False,
        evidence_head_sha="a" * 40,
        current_head_sha="b" * 40,
    )
    assert reason is AdjudicationReason.NOT_INDEPENDENT


@pytest.mark.parametrize(
    "forbidden",
    ["verdict", "merge", "labels", "ci_waiver", "hitl_override", "approved"],
)
def test_a_proposal_has_no_field_for_authority(forbidden: str) -> None:
    """Unreachable by absence, not by validation — a field that exists can be set."""
    with pytest.raises(ValidationError):
        ReviewProposal(recommended=ReviewVerdict.APPROVE, **{forbidden: True})


def test_a_proposal_is_frozen() -> None:
    with pytest.raises(ValidationError):
        _CLEAN.recommended = ReviewVerdict.COMMENT


def test_a_finding_is_blocking_unless_it_says_otherwise() -> None:
    """The safe default: an unmarked finding must not silently be advisory."""
    assert ReviewFinding(summary="x").blocking is True


def test_a_finding_cannot_be_empty() -> None:
    """'A finding with no content' is how a reviewer would hide one."""
    with pytest.raises(ValidationError):
        ReviewFinding(summary="")


def test_recommending_request_changes_is_never_relaxed() -> None:
    """Disagreement resolves toward the stricter reading, in both directions."""
    proposal = ReviewProposal(recommended=ReviewVerdict.REQUEST_CHANGES)
    verdict, _ = adjudicate(proposal, **_DETERMINISTIC)
    assert verdict is ReviewVerdict.REQUEST_CHANGES


def test_strictness_order_covers_every_verdict() -> None:
    """A verdict missing from STRICTER would crash _strictest at runtime."""
    assert set(STRICTER) == set(ReviewVerdict)
