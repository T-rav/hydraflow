"""Regression pin for #10011: stale agent-branch GC + false 'fix applied'
comment reconciler + unpushed-work detector.

The 2026-07-19 groom found 9+ unmerged ``origin/agent/issue-*`` /
``origin/fix/*`` branches carrying ``Fixes #N`` commits, with issue comments
claiming "fix applied" that were FALSE against staging — #9553, #9554, and
#9661 were nearly wrongly closed on that evidence. This pins the exact
classification matrix the issue's fix requires so a future refactor can't
silently regress it: unmerged+old+fixes-ref -> comment; young -> skip;
open-PR -> skip; already-commented -> dedup skip. It also pins the
destructive-action safety invariant separately — branch deletion is the
highest-blast-radius part of this feature, so its gate (default OFF, never
below the age floor) gets its own dedicated assertions rather than relying
on the broader unit suite alone.
"""

from __future__ import annotations

from branch_gc_scan import classify_branch, should_delete_branch

_BASE = {
    "issue_number": 9553,
    "age_days": 30,
    "has_open_pr": False,
    "issue_state": "OPEN",
    "already_commented": False,
    "stale_days": 3,
}


def test_unmerged_old_with_fixes_reference_comments() -> None:
    decision = classify_branch(**_BASE)
    assert decision.should_comment


def test_young_branch_is_skipped_not_commented() -> None:
    decision = classify_branch(**{**_BASE, "age_days": 1})
    assert not decision.should_comment


def test_open_pr_is_skipped_not_commented() -> None:
    decision = classify_branch(**{**_BASE, "has_open_pr": True})
    assert not decision.should_comment


def test_already_commented_branch_is_deduped_not_recommented() -> None:
    decision = classify_branch(**{**_BASE, "already_commented": True})
    assert not decision.should_comment
    assert decision.reason == "already_commented"


def test_deletion_defaults_off_regardless_of_age() -> None:
    """The single most destructive path in this feature: deletion must
    never fire while ``branch_gc_delete_enabled`` (default False) is off,
    no matter how old the branch is."""
    assert not should_delete_branch(
        age_days=10_000, min_delete_age_days=14, delete_enabled=False
    )


def test_deletion_never_fires_below_the_min_age_floor_even_when_enabled() -> None:
    """Even with the operator opt-in flipped on, a branch younger than the
    generous age floor is never deleted."""
    assert not should_delete_branch(
        age_days=13, min_delete_age_days=14, delete_enabled=True
    )
