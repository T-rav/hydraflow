"""Tests for FakeGitHub stateful fake."""

from __future__ import annotations

import pytest

from mockworld.fakes.fake_github import FakeGitHub, RateLimitError
from mockworld.seed import MockWorldSeed
from tests.conftest import TaskFactory

pytestmark = pytest.mark.scenario


class TestFakeGitHubIssues:
    def test_add_and_query_issue(self):
        gh = FakeGitHub()
        gh.add_issue(1, "Fix bug", "body", labels=["hydraflow-ready"])
        issue = gh.issue(1)
        assert issue.labels == ["hydraflow-ready"]
        assert issue.title == "Fix bug"

    def test_issue_not_found_raises(self):
        gh = FakeGitHub()
        with pytest.raises(KeyError, match="999"):
            gh.issue(999)


class TestFakeGitHubPRs:
    async def test_create_pr_tracks_state(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        assert pr.number >= 1
        assert gh.pr(pr.number).merged is False

    async def test_merge_pr_sets_merged(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        result = await gh.merge_pr(pr.number)
        assert result is True
        assert gh.pr(pr.number).merged is True

    async def test_pr_for_issue(self):
        gh = FakeGitHub()
        issue = TaskFactory.create(id=1)
        pr = await gh.create_pr(issue, "agent/issue-1")
        found = gh.pr_for_issue(1)
        assert found is not None
        assert found.number == pr.number

    async def test_wait_for_ci_default_pass(self):
        gh = FakeGitHub()
        passed, _ = await gh.wait_for_ci(100)
        assert passed is True

    async def test_wait_for_ci_scripted_failure(self):
        gh = FakeGitHub()
        gh.script_ci(100, [(False, "CI failed"), (True, "CI passed")])
        r1 = await gh.wait_for_ci(100)
        r2 = await gh.wait_for_ci(100)
        assert r1[0] is False
        assert r2[0] is True


class TestFakeGitHubBranchPrState:
    """#11502: get_branch_pr_state mirrors the seeded merged/closed flags."""

    async def test_merged_pr_reports_merged(self):
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="fix/thing", merged=True)
        assert await gh.get_branch_pr_state("fix/thing") == "MERGED"

    async def test_open_pr_reports_open(self):
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="fix/thing")
        assert await gh.get_branch_pr_state("fix/thing") == "OPEN"

    async def test_closed_unmerged_pr_reports_closed(self):
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="fix/thing")
        gh.pr(1).closed = True
        assert await gh.get_branch_pr_state("fix/thing") == "CLOSED"

    async def test_unknown_branch_reports_none(self):
        gh = FakeGitHub()
        assert await gh.get_branch_pr_state("fix/never-existed") == "NONE"


class TestFakeGitHubListAllPrs:
    """list_all_prs must reflect distinct per-PR dates (#11418 review finding).

    Before this fix, every PR was stamped with the same fixed date
    regardless of when it was seeded/merged/closed, which would silently
    defeat any age/window-boundary assertion a fitness-metric scenario
    made against list_all_prs.
    """

    async def test_distinct_created_at_per_pr_survives_list_all_prs(self):
        gh = FakeGitHub()
        gh.add_pr(
            number=1, issue_number=1, branch="b1", created_at="2026-01-01T00:00:00Z"
        )
        gh.add_pr(
            number=2, issue_number=2, branch="b2", created_at="2026-06-15T00:00:00Z"
        )

        prs = await gh.list_all_prs()

        by_number = {pr["number"]: pr for pr in prs}
        assert by_number[1]["createdAt"] == "2026-01-01T00:00:00Z"
        assert by_number[2]["createdAt"] == "2026-06-15T00:00:00Z"

    async def test_merged_at_reflects_seeded_value(self):
        gh = FakeGitHub()
        gh.add_pr(
            number=3,
            issue_number=3,
            branch="b3",
            merged=True,
            merged_at="2026-03-20T00:00:00Z",
        )

        prs = await gh.list_all_prs()

        assert prs[0]["mergedAt"] == "2026-03-20T00:00:00Z"

    async def test_unseeded_dates_fall_back_to_created_at(self):
        """Backward-compat: PRs seeded without explicit dates keep working."""
        gh = FakeGitHub()
        gh.add_pr(number=4, issue_number=4, branch="b4", merged=True)

        prs = await gh.list_all_prs()

        pr = prs[0]
        assert pr["createdAt"] == pr["closedAt"] == pr["mergedAt"]


class TestFakeGitHubMutations:
    async def test_transition_updates_labels(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-find"])
        await gh.transition(1, "plan")
        assert gh.issue(1).labels == ["hydraflow-plan"]

    @pytest.mark.parametrize(
        ("stage", "expected_label"),
        [
            ("find", "hydraflow-find"),
            ("plan", "hydraflow-plan"),
            ("ready", "hydraflow-ready"),
            ("review", "hydraflow-review"),
            ("hitl", "hydraflow-hitl"),
            ("diagnose", "hydraflow-diagnose"),
        ],
    )
    async def test_transition_applies_canonical_stage_label(
        self, stage: str, expected_label: str
    ) -> None:
        # Mirrors PRManager.transition._STAGE_LABEL — the fake must route every
        # production stage to its hydraflow-* label. A missing entry silently
        # labels the issue with the bare stage name, stranding it from the loop
        # that scans for the canonical label (the s05 diagnose-hop failure).
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-review"])
        await gh.transition(1, stage)
        assert gh.issue(1).labels == [expected_label]

    async def test_transition_diagnose_visible_to_diagnostic_loop(self) -> None:
        # The DiagnosticLoop polls list_issues_by_label("hydraflow-diagnose").
        # Review-fix-cap escalation transitions the issue to "diagnose"; if the
        # fake mislabels it, the loop never sees it and HITL never forms (s05).
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-review"])
        await gh.transition(1, "diagnose")
        found = await gh.list_issues_by_label("hydraflow-diagnose")
        assert [issue["number"] for issue in found] == [1]

    async def test_swap_pipeline_labels_removes_existing(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=["hydraflow-find", "bug"])
        await gh.swap_pipeline_labels(1, "hydraflow-plan")
        assert "hydraflow-plan" in gh.issue(1).labels
        assert "hydraflow-find" not in gh.issue(1).labels
        assert "bug" in gh.issue(1).labels  # non-pipeline labels preserved

    async def test_close_issue_sets_state(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b")
        await gh.close_issue(1)
        assert gh.issue(1).state == "closed"

    async def test_post_comment_appends_to_issue(self):
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b")
        await gh.post_comment(1, "a comment")
        assert "a comment" in gh.issue(1).comments

    async def test_list_issue_comments_returns_distinct_login_and_created_at(self):
        """Structured per-comment records (Task 5): list_issue_comments must
        surface each comment's own author + timestamp, not a hardcoded
        constant shared by every comment on the issue."""
        # Seed two structured comments via the seed loader so the test
        # exercises the same path a scenario would use.
        seed = MockWorldSeed(
            issues=[{"number": 1, "title": "t", "body": "b", "labels": []}],
            comments={
                1: [
                    {
                        "login": "alice",
                        "body": "/pause",
                        "created_at": "2026-07-01T00:00:00Z",
                    },
                    {
                        "login": "bob",
                        "body": "/resume",
                        "created_at": "2026-07-01T00:05:00Z",
                    },
                ]
            },
        )
        gh = FakeGitHub.from_seed(seed)

        comments = await gh.list_issue_comments(1)

        assert len(comments) == 2
        assert comments[0]["user"]["login"] == "alice"
        assert comments[0]["body"] == "/pause"
        assert comments[0]["created_at"] == "2026-07-01T00:00:00Z"
        assert comments[1]["user"]["login"] == "bob"
        assert comments[1]["body"] == "/resume"
        assert comments[1]["created_at"] == "2026-07-01T00:05:00Z"


class TestFakeGitHubRunGhIssueEdit:
    """#11419: FakeGitHub models ``gh issue edit <n> --body-file <path>``.

    The only real issuer is ``PRManager.update_issue_body``, which routes
    the body through a temp ``--body-file`` (``_run_with_body_file``), so
    the fake reads the file — exactly what the real gh CLI would consume.
    """

    async def test_edit_updates_body_via_run_gh(self, tmp_path):
        gh = FakeGitHub()
        gh.add_issue(42, "title", "old body")
        body_file = tmp_path / "body.md"
        body_file.write_text("new body", encoding="utf-8")

        await gh._run_gh(
            "gh",
            "issue",
            "edit",
            "42",
            "--repo",
            "o/r",
            "--body-file",
            str(body_file),
        )

        assert await gh.get_issue_body(42) == "new body"

    async def test_edit_without_body_flag_is_a_noop(self):
        gh = FakeGitHub()
        gh.add_issue(42, "title", "old body")

        await gh._run_gh("gh", "issue", "edit", "42", "--repo", "o/r")

        assert await gh.get_issue_body(42) == "old body"

    async def test_edit_with_missing_body_file_is_a_noop(self, tmp_path):
        """_run_with_body_file unlinks its temp file in a finally — a path
        that no longer resolves must not raise out of the fake."""
        gh = FakeGitHub()
        gh.add_issue(42, "title", "old body")

        await gh._run_gh(
            "gh",
            "issue",
            "edit",
            "42",
            "--repo",
            "o/r",
            "--body-file",
            str(tmp_path / "gone.md"),
        )

        assert await gh.get_issue_body(42) == "old body"


class TestFakeGitHubRateLimit:
    async def test_rate_limit_zero_remaining_raises(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0, reset_in=60)
        with pytest.raises(RateLimitError) as exc_info:
            await gh.add_labels(1, ["x"])
        assert exc_info.value.reset_in == 60
        assert exc_info.value.secondary is False

    async def test_rate_limit_nonzero_remaining_decrements(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=2, reset_in=60)
        await gh.add_labels(1, ["a"])  # remaining=1
        await gh.add_labels(1, ["b"])  # remaining=0
        with pytest.raises(RateLimitError):
            await gh.add_labels(1, ["c"])

    async def test_secondary_rate_limit_sets_flag(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0, secondary=True)
        with pytest.raises(RateLimitError) as exc_info:
            await gh.add_labels(1, ["x"])
        assert exc_info.value.secondary is True

    async def test_rate_limit_heals_via_clear(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "t", "b", labels=[])
        gh.set_rate_limit_mode(remaining=0)
        gh.clear_rate_limit()
        await gh.add_labels(1, ["x"])  # no raise
        assert "x" in gh.issue(1).labels


class TestFakeGitHubCodeScanningAlerts:
    async def test_fetch_code_scanning_alerts_returns_scripted_list(self) -> None:
        from models import CodeScanningAlert

        gh = FakeGitHub()
        alerts = [
            CodeScanningAlert(
                number=1,
                severity="error",
                security_severity="high",
                path="src/x.py",
                start_line=42,
                rule="py/sql-injection",
                message="potential injection",
            ),
        ]
        gh.add_alerts(branch="refs/heads/x", alerts=alerts)
        out = await gh.fetch_code_scanning_alerts(branch="refs/heads/x")
        assert out == alerts

    async def test_fetch_code_scanning_alerts_defaults_empty(self) -> None:
        gh = FakeGitHub()
        assert await gh.fetch_code_scanning_alerts(branch="refs/heads/missing") == []

    async def test_fetch_code_scanning_alerts_keyed_by_branch(self) -> None:
        """Alerts are keyed by branch string, matching PRPort.fetch_code_scanning_alerts."""
        from models import CodeScanningAlert

        gh = FakeGitHub()
        a1 = CodeScanningAlert(
            number=1,
            severity="error",
            security_severity="high",
            path="a.py",
            start_line=1,
            rule="r1",
            message="m1",
        )
        a2 = CodeScanningAlert(
            number=2,
            severity="warning",
            security_severity="medium",
            path="b.py",
            start_line=2,
            rule="r2",
            message="m2",
        )
        gh.add_alerts(branch="agent/issue-1", alerts=[a1])
        gh.add_alerts(branch="agent/issue-2", alerts=[a2])

        out1 = await gh.fetch_code_scanning_alerts(branch="agent/issue-1")
        out2 = await gh.fetch_code_scanning_alerts(branch="agent/issue-2")
        assert out1 == [a1]
        assert out2 == [a2]
