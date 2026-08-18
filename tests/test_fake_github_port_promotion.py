"""FakeGitHub fidelity for the #11418/#11419 PRPort-boundary promotion.

Five raw ``gh`` CLI shapes that loops used to reach for via
``self._prs._run_gh(...)``/``self._prs._repo`` are now real ``PRPort``
methods (``list_branch_refs``, ``list_branch_commits``, ``get_issue_body``,
``list_all_issues_for_fitness``, ``list_all_prs_for_fitness``) that
``FakeGitHub`` implements directly instead of an always-empty
``_run_gh``/``_modelled_api_payload`` stand-in. ``_run_gh`` also now models
``gh issue edit --body`` (#11419), closing the last unmodelled shape
``ReportIssueLoop`` depended on before its own promotion to
``update_issue_body``.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from mockworld.fakes.fake_github import FakeGitHub, FakeGitHubUnmodelledCommand


class TestListBranchRefs:
    @pytest.mark.asyncio
    async def test_filters_by_prefix(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="agent/issue-1")
        gh.add_pr(number=2, issue_number=2, branch="fix/thing")

        refs = await gh.list_branch_refs("agent/issue-")

        assert refs == ["agent/issue-1"]

    @pytest.mark.asyncio
    async def test_no_matching_branches_returns_empty(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="fix/thing")

        assert await gh.list_branch_refs("agent/issue-") == []

    @pytest.mark.asyncio
    async def test_ignores_pr_lifecycle_state(self) -> None:
        """A closed/merged PR's branch still registers — matching-refs
        lists refs by name regardless of PR state, mirroring a real
        ``git/matching-refs`` read."""
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="agent/issue-1", merged=True)

        assert await gh.list_branch_refs("agent/issue-") == ["agent/issue-1"]


class TestListBranchCommits:
    @pytest.mark.asyncio
    async def test_unseeded_branch_returns_empty(self) -> None:
        """Honest 'no commits recorded' default — mirrors a real 404,
        not a silent fabricated commit."""
        gh = FakeGitHub()

        assert await gh.list_branch_commits("agent/issue-1") == []

    @pytest.mark.asyncio
    async def test_seeded_commits_read_back_newest_first(self) -> None:
        gh = FakeGitHub()
        gh.add_branch_commits(
            "agent/issue-1",
            [
                {"date": "2026-01-02T00:00:00Z", "message": "Fixes #1: thing"},
                {"date": "2026-01-01T00:00:00Z", "message": "wip"},
            ],
        )

        commits = await gh.list_branch_commits("agent/issue-1")

        assert commits == [
            {"date": "2026-01-02T00:00:00Z", "message": "Fixes #1: thing"},
            {"date": "2026-01-01T00:00:00Z", "message": "wip"},
        ]

    @pytest.mark.asyncio
    async def test_seeding_is_per_branch(self) -> None:
        gh = FakeGitHub()
        gh.add_branch_commits("agent/issue-1", [{"date": "d", "message": "m"}])

        assert await gh.list_branch_commits("agent/issue-2") == []


class TestGetIssueBody:
    @pytest.mark.asyncio
    async def test_returns_seeded_body(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(42, "title", "the body text")

        assert await gh.get_issue_body(42) == "the body text"

    @pytest.mark.asyncio
    async def test_unknown_issue_returns_empty_string(self) -> None:
        gh = FakeGitHub()

        assert await gh.get_issue_body(999) == ""


class TestListAllIssuesForFitness:
    @pytest.mark.asyncio
    async def test_includes_every_state(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(1, "open one", "", labels=["hydraflow-find"])
        gh.add_issue(2, "closed one", "", state="closed")

        rows = await gh.list_all_issues_for_fitness()

        numbers = {row["number"] for row in rows}
        assert numbers == {1, 2}
        by_number = {row["number"]: row for row in rows}
        assert by_number[1]["state"] == "OPEN"
        assert by_number[2]["state"] == "CLOSED"
        assert by_number[1]["labels"] == [{"name": "hydraflow-find"}]

    @pytest.mark.asyncio
    async def test_respects_limit(self) -> None:
        gh = FakeGitHub()
        for n in range(5):
            gh.add_issue(n, f"issue {n}", "")

        rows = await gh.list_all_issues_for_fitness(limit=2)

        assert len(rows) == 2


class TestListAllPrsForFitness:
    @pytest.mark.asyncio
    async def test_includes_every_state(self) -> None:
        gh = FakeGitHub()
        gh.add_pr(number=1, issue_number=1, branch="agent/issue-1")
        gh.add_pr(number=2, issue_number=2, branch="agent/issue-2", merged=True)

        rows = await gh.list_all_prs_for_fitness()

        by_number = {row["number"]: row for row in rows}
        assert by_number[1]["state"] == "OPEN"
        assert by_number[1]["mergedAt"] is None
        assert by_number[2]["state"] == "MERGED"
        assert by_number[2]["mergedAt"] is not None


class TestRunGhIssueEdit:
    """#11419: FakeGitHub models ``gh issue edit --body`` directly on
    ``_run_gh`` — the general fidelity fix, independent of any one call
    site (ReportIssueLoop's own reach-around was separately promoted to
    ``update_issue_body`` by #11418)."""

    @pytest.mark.asyncio
    async def test_edit_updates_body_via_run_gh(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(42, "title", "old body")

        await gh._run_gh(
            "gh", "issue", "edit", "42", "--repo", "o/r", "--body", "new body"
        )

        assert await gh.get_issue_body(42) == "new body"

    @pytest.mark.asyncio
    async def test_edit_without_body_flag_is_a_noop(self) -> None:
        gh = FakeGitHub()
        gh.add_issue(42, "title", "old body")

        await gh._run_gh("gh", "issue", "edit", "42", "--repo", "o/r")

        assert await gh.get_issue_body(42) == "old body"


class TestBranchGcApiShapesNoLongerModelled:
    """#11418: since StaleIssueLoop's branch-GC now calls the real Port
    methods instead of raw ``gh api`` shapes, the interim (#11413/#11417)
    ``_run_gh``/``_modelled_api_payload`` matching-refs/commits stand-in is
    gone — those raw shapes fail loud like any other unmodelled command."""

    @pytest.mark.asyncio
    async def test_raw_matching_refs_shape_now_fails_loud(self) -> None:
        gh = FakeGitHub()

        with pytest.raises(FakeGitHubUnmodelledCommand):
            await gh._run_gh(
                "gh",
                "api",
                "repos/o/r/git/matching-refs/heads/agent/",
                "--jq",
                "[.[].ref]",
            )

    @pytest.mark.asyncio
    async def test_raw_commits_shape_now_fails_loud(self) -> None:
        gh = FakeGitHub()

        with pytest.raises(FakeGitHubUnmodelledCommand):
            await gh._run_gh("gh", "api", "repos/o/r/commits", "--method", "GET")
