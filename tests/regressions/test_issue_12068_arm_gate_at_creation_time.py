"""#12068: the auto-merge gate could never pass at the moment it is consulted.

`open_automated_pr` arms `--auto` in the same breath as `gh pr create`
returns. The #10672 belt asked "is EVERY non-skipped check settled SUCCESS?",
which at that instant is always False: `.github/workflows/ci.yml` triggers on
`pull_request`, so the checks are either unregistered (empty rollup) or queued.
So `gh pr merge --auto` was never issued and every PR from DiagramLoop,
RepoWikiLoop, the UL terms loop, ADR acceptance, arch regen and prompt refine
was left open indefinitely.

Measured, not argued: fed PR #12100's live rollup — taken twelve minutes after
creation, 30 of 36 checks COMPLETED and all of those SUCCESS or SKIPPED — to
the production classifier, which returned False.

The belt's purpose survives: #10663's harm was arming on a PR already known to
be bad, and a settled failing check still refuses. What holds everything else
is branch protection, verified live rather than assumed — the active
`staging protect` ruleset requires `CI Gate`, `quality (.)`, `quality
(src/ui)`, `Detect Changes` and `discover-projects`.
"""

from __future__ import annotations

from auto_pr import _rollup_has_settled_failure, _status_check_rollup_is_green

_QUEUED = {"status": "QUEUED", "conclusion": None, "name": "CI Gate"}
_RUNNING = {"status": "IN_PROGRESS", "conclusion": None, "name": "quality (.)"}
_PASSED = {"status": "COMPLETED", "conclusion": "SUCCESS", "name": "Detect Changes"}
_FAILED = {"status": "COMPLETED", "conclusion": "FAILURE", "name": "CI Gate"}


def test_a_freshly_created_pr_is_armable() -> None:
    """The empty rollup is the shape at `gh pr create` + 0s."""
    assert _rollup_has_settled_failure([]) is False


def test_a_pr_mid_ci_is_armable() -> None:
    """The realistic shape: some settled green, the rest still running."""
    rollup = [_PASSED, _QUEUED, _RUNNING]

    assert _rollup_has_settled_failure(rollup) is False


def test_a_settled_failure_is_still_refused() -> None:
    """#10663's harm — arming on a PR already known bad — stays prevented."""
    assert _rollup_has_settled_failure([_PASSED, _FAILED]) is True


def test_a_queued_legacy_status_context_is_not_a_failure() -> None:
    """StatusContext entries carry no `status`, so `state` must be read.

    Without the pending-state check a queued legacy commit status reads as a
    settled non-green conclusion, which would refuse every PR that has one —
    reintroducing the bug through the other rollup shape.
    """
    assert (
        _rollup_has_settled_failure([{"state": "PENDING", "context": "legacy"}])
        is False
    )
    assert (
        _rollup_has_settled_failure([{"state": "EXPECTED", "context": "legacy"}])
        is False
    )
    assert (
        _rollup_has_settled_failure([{"state": "FAILURE", "context": "legacy"}]) is True
    )


def test_the_green_predicate_is_unchanged_and_still_strict() -> None:
    """The decoy, and the reason this is a new predicate rather than an edit.

    `_status_check_rollup_is_green` answers "is this PR green NOW", which is a
    real question with real callers' expectations pinned in
    test_issue_10672.py. The bug was using it for the ARM decision. If someone
    "simplifies" by pointing the arm gate back at it, or by loosening it so
    the arm gate passes, these assertions fail.
    """
    assert _status_check_rollup_is_green([]) is False
    assert _status_check_rollup_is_green([_PASSED, _QUEUED]) is False
    assert _status_check_rollup_is_green([_PASSED]) is True
