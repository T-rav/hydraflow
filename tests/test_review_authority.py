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

_CLEAN = ReviewProposal(recommended=ReviewVerdict.APPROVE)
_BLOCKING = ReviewProposal(
    recommended=ReviewVerdict.APPROVE,
    findings=(ReviewFinding(summary="null deref on the empty path"),),
)


def test_a_clean_proposal_with_green_ci_is_approved() -> None:
    verdict, reason = adjudicate(_CLEAN, ci_green=True)
    assert verdict is ReviewVerdict.APPROVE
    assert reason is AdjudicationReason.RECOMMENDATION_ACCEPTED


def test_a_reviewer_cannot_self_approve_over_its_own_blocking_finding() -> None:
    verdict, reason = adjudicate(_BLOCKING, ci_green=True)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.FINDINGS_PRESENT


def test_advisory_findings_cap_an_approval_at_comment() -> None:
    proposal = ReviewProposal(
        recommended=ReviewVerdict.APPROVE,
        findings=(ReviewFinding(summary="nit: naming", blocking=False),),
    )
    verdict, _ = adjudicate(proposal, ci_green=True)
    assert verdict is ReviewVerdict.COMMENT


def test_a_reviewer_cannot_approve_past_red_ci() -> None:
    verdict, reason = adjudicate(_CLEAN, ci_green=False)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.CI_NOT_GREEN


def test_a_reviewer_cannot_approve_past_a_hitl_requirement() -> None:
    verdict, reason = adjudicate(_CLEAN, ci_green=True, hitl_required=True)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.HITL_REQUIRED


def test_a_non_independent_reviewer_cannot_approve() -> None:
    verdict, reason = adjudicate(_CLEAN, ci_green=True, reviewer_independent=False)
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.NOT_INDEPENDENT


def test_a_review_of_a_moved_snapshot_is_not_a_review_of_what_would_merge() -> None:
    verdict, reason = adjudicate(
        _CLEAN, ci_green=True, evidence_head_sha="a" * 40, current_head_sha="b" * 40
    )
    assert verdict is ReviewVerdict.REQUEST_CHANGES
    assert reason is AdjudicationReason.EVIDENCE_STALE


def test_a_matching_snapshot_does_not_block() -> None:
    verdict, _ = adjudicate(
        _CLEAN, ci_green=True, evidence_head_sha="a" * 40, current_head_sha="a" * 40
    )
    assert verdict is ReviewVerdict.APPROVE


def test_an_unplumbed_snapshot_pair_is_not_treated_as_a_match() -> None:
    """Both empty means 'not checked', and must not read as 'matched'."""
    verdict, reason = adjudicate(_CLEAN, ci_green=True)
    assert reason is not AdjudicationReason.EVIDENCE_STALE
    assert verdict is ReviewVerdict.APPROVE

    # One side supplied is still not a comparison, so it must not block either.
    verdict, _ = adjudicate(_CLEAN, ci_green=True, evidence_head_sha="a" * 40)
    assert verdict is ReviewVerdict.APPROVE


def test_a_reviewer_cannot_downgrade_a_deterministic_block() -> None:
    """The recommendation loses to every deterministic constraint, not just some."""
    for kwargs in (
        {"ci_green": False},
        {"ci_green": True, "hitl_required": True},
        {"ci_green": True, "reviewer_independent": False},
    ):
        verdict, _ = adjudicate(
            ReviewProposal(recommended=ReviewVerdict.APPROVE), **kwargs
        )
        assert verdict is ReviewVerdict.REQUEST_CHANGES, kwargs


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
    verdict, _ = adjudicate(proposal, ci_green=True)
    assert verdict is ReviewVerdict.REQUEST_CHANGES


def test_strictness_order_covers_every_verdict() -> None:
    """A verdict missing from STRICTER would crash _strictest at runtime."""
    assert set(STRICTER) == set(ReviewVerdict)
