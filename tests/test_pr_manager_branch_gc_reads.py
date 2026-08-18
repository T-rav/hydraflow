"""Tests for the PRPort reach-through retirement reads (#11418).

``list_branch_refs`` / ``list_branch_commits`` / ``get_issue_body`` /
``list_all_issues`` / ``list_all_prs`` replace raw ``self._prs._run_gh`` /
``self._prs._repo`` cross-module reach-throughs in StaleIssueLoop,
ReportIssueLoop, and service_registry's fitness fetcher with first-class
Port methods PRManager and FakeGitHub both implement.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import AsyncMock, MagicMock

import pytest

from tests.helpers import ConfigFactory, make_pr_manager


def _build(tmp_path: Path):
    cfg = ConfigFactory.create(
        repo_root=tmp_path,
        workspace_base=tmp_path / "wt",
        state_file=tmp_path / "s.json",
        repo="owner/repo",
    )
    bus = MagicMock()
    bus.publish = AsyncMock()
    return make_pr_manager(cfg, bus)


class TestListBranchRefs:
    async def test_returns_branch_and_sha_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            assert "matching-refs/heads/agent/issue-" in args[2]
            return (
                '[{"ref": "refs/heads/agent/issue-42", "sha": "abc"},'
                ' {"ref": "refs/heads/agent/issue-43", "sha": "def"}]'
            )

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        refs = await pm.list_branch_refs("agent/issue-")
        assert refs == [("agent/issue-42", "abc"), ("agent/issue-43", "def")]

    async def test_empty_response_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(pm, "_run_gh", AsyncMock(return_value=""))
        assert await pm.list_branch_refs("fix/") == []

    async def test_propagates_gh_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(
            pm, "_run_gh", AsyncMock(side_effect=RuntimeError("gh boom"))
        )
        with pytest.raises(RuntimeError, match="gh boom"):
            await pm.list_branch_refs("agent/issue-")


class TestListBranchCommits:
    async def test_returns_date_message_pairs(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            assert "repos/owner/repo/commits" in args[2]
            assert "sha=agent/issue-42" in args
            assert "per_page=30" in args
            return (
                '[{"date": "2026-08-01T00:00:00Z", "message": "Fixes #42: foo"},'
                ' {"date": "2026-07-31T00:00:00Z", "message": "wip"}]'
            )

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        commits = await pm.list_branch_commits("agent/issue-42")
        assert commits == [
            {"date": "2026-08-01T00:00:00Z", "message": "Fixes #42: foo"},
            {"date": "2026-07-31T00:00:00Z", "message": "wip"},
        ]

    async def test_respects_limit_param(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        captured: list[tuple] = []

        async def fake_gh(*args, **_kwargs):
            captured.append(args)
            return "[]"

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        await pm.list_branch_commits("agent/issue-42", limit=5)
        assert "per_page=5" in captured[0]

    async def test_no_commits_returns_empty_list(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(pm, "_run_gh", AsyncMock(return_value="[]"))
        assert await pm.list_branch_commits("agent/issue-42") == []


class TestGetIssueBody:
    async def test_returns_body_text(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            assert "issue" in args and "view" in args
            assert "42" in args
            return '{"body": "some body text"}'

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.get_issue_body(42) == "some body text"

    async def test_propagates_gh_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(
            pm, "_run_gh", AsyncMock(side_effect=RuntimeError("no such issue"))
        )
        with pytest.raises(RuntimeError, match="no such issue"):
            await pm.get_issue_body(42)

    async def test_json_null_body_returns_empty_string_not_the_string_none(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """gh returns {"body": null} for issues with no description — must
        map to "", not str(None) == "None" (#11418 review finding)."""
        pm = _build(tmp_path)
        monkeypatch.setattr(pm, "_run_gh", AsyncMock(return_value='{"body": null}'))
        assert await pm.get_issue_body(42) == ""


class TestListAllIssues:
    async def test_returns_parsed_issue_dicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            assert "--state" in args
            assert "open" in args
            assert "--limit" in args
            assert "100" in args
            return '[{"number": 1, "title": "t", "state": "OPEN", "labels": [], "createdAt": "2026-01-01T00:00:00Z", "updatedAt": "2026-01-02T00:00:00Z", "closedAt": null}]'

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        issues = await pm.list_all_issues(state="open", limit=100)
        assert issues == [
            {
                "number": 1,
                "title": "t",
                "state": "OPEN",
                "labels": [],
                "createdAt": "2026-01-01T00:00:00Z",
                "updatedAt": "2026-01-02T00:00:00Z",
                "closedAt": None,
            }
        ]

    async def test_defaults_to_state_all_and_empty_on_no_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        captured: list[tuple] = []

        async def fake_gh(*args, **_kwargs):
            captured.append(args)
            return ""

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        assert await pm.list_all_issues() == []
        assert "all" in captured[0]

    async def test_propagates_gh_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(
            pm, "_run_gh", AsyncMock(side_effect=RuntimeError("rate limited"))
        )
        with pytest.raises(RuntimeError, match="rate limited"):
            await pm.list_all_issues()


class TestListAllPrs:
    async def test_returns_parsed_pr_dicts(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)

        async def fake_gh(*args, **_kwargs):
            assert "pr" in args and "list" in args
            assert "--state" in args
            assert "all" in args
            return '[{"number": 5, "state": "MERGED", "labels": [], "createdAt": "2026-01-01T00:00:00Z", "closedAt": "2026-01-03T00:00:00Z", "mergedAt": "2026-01-03T00:00:00Z"}]'

        monkeypatch.setattr(pm, "_run_gh", fake_gh)
        prs = await pm.list_all_prs()
        assert prs == [
            {
                "number": 5,
                "state": "MERGED",
                "labels": [],
                "createdAt": "2026-01-01T00:00:00Z",
                "closedAt": "2026-01-03T00:00:00Z",
                "mergedAt": "2026-01-03T00:00:00Z",
            }
        ]

    async def test_empty_on_no_output(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        pm = _build(tmp_path)
        monkeypatch.setattr(pm, "_run_gh", AsyncMock(return_value=""))
        assert await pm.list_all_prs() == []
