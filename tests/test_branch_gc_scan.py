"""Unit tests for the pure branch-GC scan/classify engine (#10011).

Covers issue-number extraction (branch-name vs commit-message), the
classification decision matrix (unmerged+old+fixes-ref -> comment; young ->
skip; open-PR -> skip; already-commented -> dedup skip) that P10.6 requires
as a regression test, the deletion age-floor gate, and the local
unpushed-branch parser.
"""

from __future__ import annotations

from branch_gc_scan import (
    BranchGCDecision,
    UnpushedBranch,
    build_truth_comment,
    classify_branch,
    extract_issue_number,
    parse_unpushed_branches,
    should_delete_branch,
)

# ---------------------------------------------------------------------------
# extract_issue_number
# ---------------------------------------------------------------------------


class TestExtractIssueNumber:
    def test_agent_issue_branch_uses_branch_name(self) -> None:
        assert extract_issue_number("agent/issue-9553", []) == 9553

    def test_agent_issue_branch_ignores_commit_messages(self) -> None:
        # Branch-name encoding wins even if a commit message references a
        # different issue (e.g. a follow-up fix bundled into the same branch).
        assert extract_issue_number("agent/issue-9553", ["Fixes #1111"]) == 9553

    def test_fix_branch_scans_commit_messages_for_fixes_keyword(self) -> None:
        messages = ["wip", "Fixes #9965: regression collection"]
        assert extract_issue_number("fix/regression-collection", messages) == 9965

    def test_fix_branch_accepts_closes_and_resolves_keywords(self) -> None:
        assert extract_issue_number("fix/x", ["Closes #42"]) == 42
        assert extract_issue_number("fix/y", ["resolves #43"]) == 43

    def test_fix_branch_newest_first_order_wins(self) -> None:
        # commit_messages is newest-first; the first match found wins.
        messages = ["Fixes #2: latest", "Fixes #1: original"]
        assert extract_issue_number("fix/x", messages) == 2

    def test_no_reference_anywhere_returns_zero(self) -> None:
        assert extract_issue_number("fix/unrelated", ["just a commit"]) == 0

    def test_agent_prefix_without_digits_falls_back_to_messages(self) -> None:
        # "agent/issue-" without a trailing number doesn't match the regex —
        # falls through to message scanning like any other branch.
        assert extract_issue_number("agent/issue-abc", ["Fixes #7"]) == 7


# ---------------------------------------------------------------------------
# classify_branch — the decision matrix
# ---------------------------------------------------------------------------


class TestClassifyBranch:
    def _decide(self, **overrides) -> BranchGCDecision:
        params = {
            "issue_number": 9553,
            "age_days": 30,
            "has_open_pr": False,
            "issue_state": "OPEN",
            "already_commented": False,
            "stale_days": 3,
        }
        params.update(overrides)
        return classify_branch(**params)

    def test_no_reference_skips(self) -> None:
        decision = self._decide(issue_number=0)
        assert decision.reason == "no_reference"
        assert not decision.should_comment
        assert not decision.eligible_for_delete_check

    def test_open_pr_skips_even_when_old(self) -> None:
        decision = self._decide(has_open_pr=True, age_days=100)
        assert decision.reason == "open_pr"
        assert not decision.should_comment
        assert not decision.eligible_for_delete_check

    def test_resolved_issue_skips(self) -> None:
        for state in ("COMPLETED", "NOT_PLANNED", "UNKNOWN", ""):
            decision = self._decide(issue_state=state)
            assert decision.reason == "resolved", state
            assert not decision.should_comment

    def test_young_branch_skips(self) -> None:
        decision = self._decide(age_days=1, stale_days=3)
        assert decision.reason == "young"
        assert not decision.should_comment

    def test_unmerged_old_with_reference_comments(self) -> None:
        decision = self._decide(age_days=10, stale_days=3)
        assert decision.reason == "comment"
        assert decision.should_comment
        assert not decision.eligible_for_delete_check

    def test_already_commented_is_a_dedup_skip(self) -> None:
        decision = self._decide(age_days=10, stale_days=3, already_commented=True)
        assert decision.reason == "already_commented"
        assert not decision.should_comment
        # But it IS still eligible for the delete-or-escalate phase.
        assert decision.eligible_for_delete_check

    def test_already_commented_still_respects_open_pr(self) -> None:
        # A PR opened after the truth comment must block delete eligibility,
        # not just the (already-satisfied) comment step.
        decision = self._decide(already_commented=True, has_open_pr=True)
        assert decision.reason == "open_pr"
        assert not decision.eligible_for_delete_check

    def test_already_commented_still_respects_resolved_issue(self) -> None:
        decision = self._decide(already_commented=True, issue_state="COMPLETED")
        assert decision.reason == "resolved"
        assert not decision.eligible_for_delete_check


# ---------------------------------------------------------------------------
# should_delete_branch — the destructive-action gate
# ---------------------------------------------------------------------------


class TestShouldDeleteBranch:
    def test_disabled_never_deletes(self) -> None:
        assert not should_delete_branch(
            age_days=999, min_delete_age_days=14, delete_enabled=False
        )

    def test_enabled_but_too_young_does_not_delete(self) -> None:
        assert not should_delete_branch(
            age_days=13, min_delete_age_days=14, delete_enabled=True
        )

    def test_enabled_and_old_enough_deletes(self) -> None:
        assert should_delete_branch(
            age_days=14, min_delete_age_days=14, delete_enabled=True
        )


def test_build_truth_comment_cites_branch_and_age() -> None:
    body = build_truth_comment("agent/issue-9553", 30)
    assert "agent/issue-9553" in body
    assert "30 days" in body
    assert "unverified" in body.lower()


# ---------------------------------------------------------------------------
# parse_unpushed_branches — local git for-each-ref parser
# ---------------------------------------------------------------------------


class TestParseUnpushedBranches:
    def test_ahead_branch_is_reported(self) -> None:
        output = "fix/regression-collection|origin/fix/regression-collection|[ahead 6, behind 1]"
        result = parse_unpushed_branches(output)
        assert result == [
            UnpushedBranch(
                branch="fix/regression-collection",
                upstream="origin/fix/regression-collection",
                ahead=6,
            )
        ]

    def test_gone_upstream_is_not_reported(self) -> None:
        # Upstream ref deleted (typically after merge) — not unpushed work.
        output = "agent/issue-8693|origin/agent/issue-8693|[gone]"
        assert parse_unpushed_branches(output) == []

    def test_in_sync_branch_is_not_reported(self) -> None:
        output = "main|origin/main|"
        assert parse_unpushed_branches(output) == []

    def test_branch_with_no_upstream_is_not_reported(self) -> None:
        output = "scratch||"
        assert parse_unpushed_branches(output) == []

    def test_behind_only_is_not_reported(self) -> None:
        output = "old-branch|origin/old-branch|[behind 5]"
        assert parse_unpushed_branches(output) == []

    def test_multiple_lines_mixed(self) -> None:
        output = "\n".join(
            [
                "main|origin/main|[ahead 1, behind 190]",
                "clean|origin/clean|",
                "gone-branch|origin/gone-branch|[gone]",
                "",
            ]
        )
        result = parse_unpushed_branches(output)
        assert [b.branch for b in result] == ["main"]
        assert result[0].ahead == 1

    def test_empty_output(self) -> None:
        assert parse_unpushed_branches("") == []
