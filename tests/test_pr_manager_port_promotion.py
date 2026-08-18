"""Tests for the PRPort-boundary promotion of raw ``_run_gh``/``_repo``
reach-arounds (#11418): ``list_branch_refs``, ``list_branch_commits``,
``get_issue_body``, ``list_all_issues_for_fitness``, and
``list_all_prs_for_fitness`` on ``PRManager``.

Each of these methods used to live as inline ``gh`` CLI shapes at the call
site (``StaleIssueLoop``, ``ReportIssueLoop``, ``service_registry.py``),
reaching around ``PRPort`` via ``self._prs._run_gh(...)`` /
``self._prs._repo``. They are now real ``PRManager`` methods declared on
``PRPort``, so FakeGitHub can model them by construction.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest

from tests.conftest import SubprocessMockBuilder
from tests.helpers import make_pr_manager


class TestListBranchRefs:
    @pytest.mark.asyncio
    async def test_strips_refs_heads_prefix(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        raw = json.dumps(["refs/heads/agent/issue-1", "refs/heads/agent/issue-2"])
        mock_create = SubprocessMockBuilder().with_stdout(raw).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_branch_refs("agent/issue-")

        assert result == ["agent/issue-1", "agent/issue-2"]

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_list(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_branch_refs("fix/")

        assert result == []

    @pytest.mark.asyncio
    async def test_queries_matching_refs_api(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock_create) as m:
            await mgr.list_branch_refs("agent/issue-")

        call_args = m.call_args[0]
        assert any("git/matching-refs/heads/agent/issue-" in str(a) for a in call_args)

    @pytest.mark.asyncio
    async def test_read_failure_propagates(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("gh boom").build()
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError),
        ):
            await mgr.list_branch_refs("agent/issue-")


class TestListBranchCommits:
    @pytest.mark.asyncio
    async def test_parses_date_message_rows(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        raw = json.dumps(
            [
                {"date": "2026-01-02T00:00:00Z", "message": "Fixes #42: thing"},
                {"date": "2026-01-01T00:00:00Z", "message": "wip"},
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(raw).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_branch_commits("agent/issue-42")

        assert result == [
            {"date": "2026-01-02T00:00:00Z", "message": "Fixes #42: thing"},
            {"date": "2026-01-01T00:00:00Z", "message": "wip"},
        ]

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_list(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_branch_commits("agent/issue-42")

        assert result == []

    @pytest.mark.asyncio
    async def test_queries_commits_api_with_get_method(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock_create) as m:
            await mgr.list_branch_commits("agent/issue-42")

        call_args = [str(a) for a in m.call_args[0]]
        assert any("/commits" in a for a in call_args)
        assert "--method" in call_args
        assert "GET" in call_args
        assert "sha=agent/issue-42" in call_args

    @pytest.mark.asyncio
    async def test_read_failure_propagates(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("gh boom").build()
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError),
        ):
            await mgr.list_branch_commits("agent/issue-42")


class TestGetIssueBody:
    @pytest.mark.asyncio
    async def test_returns_body_text(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("Some body text\n").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.get_issue_body(42)

        assert result == "Some body text"

    @pytest.mark.asyncio
    async def test_queries_body_via_issue_view(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create) as m:
            await mgr.get_issue_body(99)

        call_args = [str(a) for a in m.call_args[0]]
        assert "99" in call_args
        assert "issue" in call_args
        assert "view" in call_args
        assert ".body" in call_args

    @pytest.mark.asyncio
    async def test_read_failure_propagates(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = (
            SubprocessMockBuilder().with_returncode(1).with_stderr("gh boom").build()
        )

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            pytest.raises(RuntimeError),
        ):
            await mgr.get_issue_body(42)


class TestListAllIssuesForFitness:
    @pytest.mark.asyncio
    async def test_returns_raw_rows(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        raw = json.dumps(
            [
                {
                    "number": 1,
                    "state": "OPEN",
                    "labels": [{"name": "hydraflow-find"}],
                    "createdAt": "2026-01-01T00:00:00Z",
                    "closedAt": None,
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(raw).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_all_issues_for_fitness(1000)

        assert result[0]["number"] == 1
        assert result[0]["state"] == "OPEN"

    @pytest.mark.asyncio
    async def test_queries_all_states(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock_create) as m:
            await mgr.list_all_issues_for_fitness(1000)

        call_args = [str(a) for a in m.call_args[0]]
        assert "issue" in call_args
        assert "list" in call_args
        assert "all" in call_args

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_list(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_all_issues_for_fitness(1000)

        assert result == []


class TestListAllPrsForFitness:
    @pytest.mark.asyncio
    async def test_returns_raw_rows(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        raw = json.dumps(
            [
                {
                    "number": 7,
                    "state": "MERGED",
                    "labels": [],
                    "createdAt": "2026-01-01T00:00:00Z",
                    "closedAt": "2026-01-02T00:00:00Z",
                    "mergedAt": "2026-01-02T00:00:00Z",
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(raw).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_all_prs_for_fitness(1000)

        assert result[0]["number"] == 7
        assert result[0]["mergedAt"] == "2026-01-02T00:00:00Z"

    @pytest.mark.asyncio
    async def test_queries_all_states(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("[]").build()

        with patch("asyncio.create_subprocess_exec", mock_create) as m:
            await mgr.list_all_prs_for_fitness(1000)

        call_args = [str(a) for a in m.call_args[0]]
        assert "pr" in call_args
        assert "list" in call_args
        assert "all" in call_args

    @pytest.mark.asyncio
    async def test_empty_output_returns_empty_list(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        mock_create = SubprocessMockBuilder().with_stdout("").build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_all_prs_for_fitness(1000)

        assert result == []


class TestListOpenIssuesCarriesCreatedAt:
    """#11418: list_open_issues now projects created_at (backlog-budget needs it)."""

    @pytest.mark.asyncio
    async def test_projects_created_at(self, config, event_bus) -> None:
        mgr = make_pr_manager(config, event_bus)
        raw = json.dumps(
            [
                {
                    "number": 5,
                    "title": "t",
                    "body": "",
                    "labels": [],
                    "updatedAt": "2026-01-02T00:00:00Z",
                    "createdAt": "2026-01-01T00:00:00Z",
                }
            ]
        )
        mock_create = SubprocessMockBuilder().with_stdout(raw).build()

        with patch("asyncio.create_subprocess_exec", mock_create):
            result = await mgr.list_open_issues()

        assert result[0]["created_at"] == "2026-01-01T00:00:00Z"
