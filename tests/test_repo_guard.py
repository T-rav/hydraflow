"""Tests for cross-repo safety guardrails.

Covers config validation, PRManager guards, EventBus repo injection,
log formatter repo/session fields, and worktree origin validation.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from config import _validate_repo_format
from events import EventBus, EventType, HydraFlowEvent
from log import JSONFormatter
from tests.workspace_patch import expect_unconsulted

# ---------------------------------------------------------------------------
# Config: repo format validation
# ---------------------------------------------------------------------------


class TestValidateRepoFormat:
    def test_valid_owner_repo_passes(self) -> None:
        result = _validate_repo_format("owner/repo")
        assert result is None  # no exception raised for valid format

    def test_valid_with_dots_hyphens_underscores(self) -> None:
        result = _validate_repo_format("my-org.com/my_repo-v2")
        assert result is None  # no exception raised for valid format

    def test_empty_string_allowed(self) -> None:
        result = _validate_repo_format("")
        assert result is None  # no exception raised for empty string

    @pytest.mark.parametrize(
        ("value", "match"),
        [
            ("just-a-name", "expected 'owner/repo'"),
            ("a/b/c", "expected 'owner/repo'"),
            ("../evil", "path traversal"),
            ("owner/..repo", "path traversal"),
        ],
        ids=[
            "no_slash_raises",
            "triple_slash_raises",
            "path_traversal_raises",
            "dotdot_in_repo_raises",
        ],
    )
    def test_rejects(self, value: str, match: str) -> None:
        with pytest.raises(ValueError, match=match):
            _validate_repo_format(value)


# ---------------------------------------------------------------------------
# PRManager: _assert_repo guard
# ---------------------------------------------------------------------------


class TestPRManagerAssertRepo:
    def _make_pr_manager(self, repo: str = "owner/repo"):
        from pr_manager import PRManager

        config = MagicMock()
        config.repo = repo
        config.gh_max_retries = 1
        config.dry_run = False
        bus = MagicMock()
        return PRManager(config, bus)

    def test_valid_repo_passes(self) -> None:
        pm = self._make_pr_manager("owner/repo")
        result = pm._assert_repo()  # should not raise
        assert result is None  # no exception raised for valid repo

    def test_empty_repo_raises(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            pm._assert_repo()

    def test_malformed_repo_raises(self) -> None:
        pm = self._make_pr_manager("bad-repo")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            pm._assert_repo()

    @pytest.mark.asyncio
    async def test_create_pr_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        issue = MagicMock()
        issue.number = 1
        issue.title = "Test"
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.create_pr(issue, "branch-1")

    @pytest.mark.asyncio
    async def test_push_branch_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.push_branch(Path("/tmp"), "branch-1")  # noqa: S108

    @pytest.mark.asyncio
    async def test_swap_labels_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.swap_pipeline_labels(1, "hydraflow-review")

    @pytest.mark.asyncio
    async def test_merge_pr_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.merge_pr(1)

    @pytest.mark.asyncio
    async def test_close_issue_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.close_issue(1)

    @pytest.mark.asyncio
    async def test_create_issue_calls_assert_repo(self) -> None:
        pm = self._make_pr_manager("")
        with pytest.raises(RuntimeError, match="repo is not configured"):
            await pm.create_issue("title", "body")


# ---------------------------------------------------------------------------
# EventBus: repo auto-injection
# ---------------------------------------------------------------------------


class TestEventBusRepoInjection:
    @pytest.mark.asyncio
    async def test_publish_injects_repo(self) -> None:
        bus = EventBus()
        bus.set_repo("owner/repo")
        event = HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"issue": 1})
        await bus.publish(event)
        assert event.repo == "owner/repo"

    @pytest.mark.asyncio
    async def test_publish_does_not_overwrite_explicit_repo(self) -> None:
        bus = EventBus()
        bus.set_repo("owner/repo")
        event = HydraFlowEvent(
            type=EventType.WORKER_UPDATE,
            data={"issue": 1},
            repo="other/repo",
        )
        await bus.publish(event)
        assert event.repo == "other/repo"

    @pytest.mark.asyncio
    async def test_publish_no_injection_when_repo_not_set(self) -> None:
        bus = EventBus()
        event = HydraFlowEvent(type=EventType.WORKER_UPDATE, data={"issue": 1})
        await bus.publish(event)
        assert event.repo is None


# ---------------------------------------------------------------------------
# JSONFormatter: repo and session fields
# ---------------------------------------------------------------------------


class TestJSONFormatterRepoSession:
    def test_repo_field_in_output(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        record.repo = "owner/repo"  # type: ignore[attr-defined]
        output = json.loads(formatter.format(record))
        assert output["repo"] == "owner/repo"

    def test_session_field_in_output(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        record.session = "sess-123"  # type: ignore[attr-defined]
        output = json.loads(formatter.format(record))
        assert output["session"] == "sess-123"

    def test_missing_repo_not_in_output(self) -> None:
        formatter = JSONFormatter()
        record = logging.LogRecord(
            name="test",
            level=logging.INFO,
            pathname="",
            lineno=0,
            msg="test message",
            args=(),
            exc_info=None,
        )
        output = json.loads(formatter.format(record))
        assert "repo" not in output
        assert "session" not in output


# ---------------------------------------------------------------------------
# Worktree: origin remote validation
# ---------------------------------------------------------------------------


class TestWorktreeOriginValidation:
    def _make_wt_manager(self, repo: str = "owner/repo"):
        from workspace import WorkspaceManager

        config = MagicMock()
        config.repo = repo
        config.repo_root = Path("/tmp/repo")  # noqa: S108
        config.repo_slug = repo.replace("/", "-") if repo else ""
        config.workspace_base = Path("/tmp/worktrees")  # noqa: S108
        config.main_branch = "main"
        config.dry_run = False
        config.ui_dirs = []
        # Prevent auto-detection from scanning filesystem
        with patch.object(WorkspaceManager, "_detect_ui_dirs", return_value=[]):
            return WorkspaceManager(config)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/owner/repo.git\n",
            "git@github.com:owner/repo.git\n",
            "https://github.com/owner/repo\n",
            "ssh://git@github.com/owner/repo.git\n",
        ],
        ids=["https", "ssh-scp", "https-no-suffix", "ssh-url"],
    )
    async def test_matching_origin_url_is_accepted(
        self, url: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        wm = self._make_wt_manager("owner/repo")
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = url
            result = await wm._assert_origin_matches_repo()
        # The mock must be the thing that answered: a stale patch target lets
        # the real subprocess run, fail, and get swallowed at _remote.py's
        # broad ``except Exception`` — ``result is None`` alone cannot tell the
        # two apart (#11547 review).
        mock_run.assert_awaited_once()
        # And the URL must have been *parsed*, not merely tolerated. Without
        # this, breaking the origin regexes leaves every case green: an
        # unparseable URL only logs a warning and returns None.
        assert "Could not parse origin URL" not in caplog.text
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "https://github.com/other/project.git\n",
            "git@github.com:other/project.git\n",
            "https://github.com/other/project\n",
        ],
        ids=["https", "ssh-scp", "https-no-suffix"],
    )
    async def test_mismatch_raises(self, url: str) -> None:
        wm = self._make_wt_manager("owner/repo")
        with patch(
            "workspace._remote.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            mock_run.return_value = url
            with pytest.raises(RuntimeError, match="expected 'owner/repo'"):
                await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()

    @pytest.mark.asyncio
    async def test_case_insensitive_match(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        wm = self._make_wt_manager("Owner/Repo")
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = "https://github.com/owner/repo.git\n"
            result = await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()
        assert "Could not parse origin URL" not in caplog.text
        assert result is None  # case-insensitive match succeeds

    @pytest.mark.asyncio
    async def test_unparseable_origin_url_warns_and_does_not_raise(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A URL neither regex understands is tolerated, loudly."""
        wm = self._make_wt_manager("owner/repo")
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = "https://gitlab.example/owner/repo.git\n"
            result = await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()
        assert "Could not parse origin URL" in caplog.text
        assert result is None

    @pytest.mark.asyncio
    async def test_empty_repo_skips_validation(self) -> None:
        wm = self._make_wt_manager("")
        with patch(
            "workspace._remote.run_subprocess", new_callable=AsyncMock
        ) as mock_run:
            result = await wm._assert_origin_matches_repo()
        # The short-circuit is the point: no subprocess is spawned at all.
        expect_unconsulted(mock_run, "empty repo short-circuits before any git call")
        assert result is None
