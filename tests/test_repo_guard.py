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

    # ------------------------------------------------------------------
    # The origin-URL table. Every form ``git remote get-url origin`` can
    # emit, including the dotted repo names (``socket.io``, ``next.js``)
    # that GitHub permits and the old ``[^/.]+?`` repo segment silently
    # refused to parse — failing this safety guard OPEN (#11703).
    # ------------------------------------------------------------------
    ORIGIN_TABLE: tuple[tuple[str, str, str], ...] = (
        # (id, origin URL as git prints it, expected owner/repo slug)
        ("scp_style", "git@github.com:owner/repo.git", "owner/repo"),
        ("scp_style_no_suffix", "git@github.com:owner/repo", "owner/repo"),
        ("https", "https://github.com/owner/repo.git", "owner/repo"),
        ("https_no_suffix", "https://github.com/owner/repo", "owner/repo"),
        ("ssh_url", "ssh://git@github.com/owner/repo.git", "owner/repo"),
        ("ssh_url_no_suffix", "ssh://git@github.com/owner/repo", "owner/repo"),
        (
            "token_in_url",
            "https://x-access-token:ghp_TOKEN@github.com/owner/repo.git",
            "owner/repo",
        ),
        # Dotted repo names — the #11703 fail-open class.
        ("dotted_scp", "git@github.com:socketio/socket.io.git", "socketio/socket.io"),
        ("dotted_https", "https://github.com/vercel/next.js", "vercel/next.js"),
        (
            "dotted_https_suffix",
            "https://github.com/vercel/next.js.git",
            "vercel/next.js",
        ),
        ("dotted_ssh_url", "ssh://git@github.com/vercel/next.js.git", "vercel/next.js"),
        ("dotted_owner", "git@github.com:my.org/my.repo.git", "my.org/my.repo"),
    )

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "slug"),
        [(url, slug) for _, url, slug in ORIGIN_TABLE],
        ids=[case_id for case_id, _, _ in ORIGIN_TABLE],
    )
    async def test_matching_origin_url_is_accepted(
        self, url: str, slug: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Every origin form parses to its slug and is accepted when it matches."""
        wm = self._make_wt_manager(slug)
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = f"{url}\n"
            result = await wm._assert_origin_matches_repo()
        # The mock must be the thing that answered: a stale patch target lets
        # the real subprocess run, fail, and get swallowed at _remote.py's
        # broad ``except Exception`` — ``result is None`` alone cannot tell the
        # two apart (#11547 review).
        mock_run.assert_awaited_once()
        # And the URL must have been *parsed*, not merely tolerated. Without
        # this, breaking the origin regex leaves every case green: an
        # unrecognised URL only logs a warning and returns None (#11703).
        assert "Origin validation SKIPPED" not in caplog.text
        assert result is None

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        ("url", "slug"),
        [(url, slug) for _, url, slug in ORIGIN_TABLE],
        ids=[case_id for case_id, _, _ in ORIGIN_TABLE],
    )
    async def test_mismatched_origin_raises_for_every_url_form(
        self, url: str, slug: str, caplog: pytest.LogCaptureFixture
    ) -> None:
        """The guard RAISES on a foreign origin — for every URL form it parses.

        The point of the guard is this raise, and #11670 found guards whose
        regression had never been watched go red. Pairing it with the accept
        table means a pattern that stops parsing a form cannot hide here: a
        skipped guard returns None, which fails ``pytest.raises`` loudly.
        """
        wm = self._make_wt_manager("owner/expected-repo")
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = f"{url}\n"
            with pytest.raises(RuntimeError) as excinfo:
                await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()
        # The message names the slug the regex extracted, so this asserts the
        # parse as well as the raise.
        assert f"resolves to {slug!r}" in str(excinfo.value)
        assert "expected 'owner/expected-repo'" in str(excinfo.value)
        assert "Origin validation SKIPPED" not in caplog.text

    @pytest.mark.asyncio
    async def test_dotted_repo_name_is_validated_not_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A dotted repo name reaches the comparison instead of failing open.

        The #11703 canary. With the old ``[^/.]+?`` repo segment this origin
        parsed to nothing, the guard warned and returned, and a checkout of the
        wrong repo sailed through. Reverting the widening must redden this.
        """
        wm = self._make_wt_manager("socketio/socket.io")
        with (
            caplog.at_level(logging.WARNING, logger="hydraflow.workspace"),
            patch(
                "workspace._remote.run_subprocess", new_callable=AsyncMock
            ) as mock_run,
        ):
            mock_run.return_value = "git@github.com:evilcorp/socket.io.git\n"
            with pytest.raises(RuntimeError, match="expected 'socketio/socket.io'"):
                await wm._assert_origin_matches_repo()
        mock_run.assert_awaited_once()
        assert "Origin validation SKIPPED" not in caplog.text

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
        assert "Origin validation SKIPPED" not in caplog.text
        assert result is None  # case-insensitive match succeeds

    @pytest.mark.asyncio
    async def test_unrecognised_origin_url_warns_that_validation_was_skipped(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """A non-GitHub origin is tolerated, and the log says the guard did not run.

        Fail-open is the deliberate, unchanged behaviour here (#11703): flipping
        it to a raise aborts factory runs on any origin form the pattern does
        not handle, which is an operator decision. What the log must NOT do is
        read like a cosmetic parse miss — it has to say the safety check was
        SKIPPED.
        """
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
        assert "Origin validation SKIPPED" in caplog.text
        assert "did NOT run" in caplog.text
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


class TestOriginUrlPatternHasNoDeadArm:
    """``_ORIGIN_SSH_RE`` was unreachable: the surviving pattern already wins.

    Deleting dead code needs proof it was dead. This asserts the property that
    made it so — ``[/:]`` matches scp-style's ``:`` and the search is unanchored
    — over the same table the behavioural tests use, so a future narrowing of
    the pattern that would resurrect the need for an SSH arm reddens here (#11703).
    """

    def test_single_pattern_parses_every_origin_form(self) -> None:
        from workspace import WorkspaceManager

        for case_id, url, slug in TestWorktreeOriginValidation.ORIGIN_TABLE:
            match = WorkspaceManager._ORIGIN_URL_RE.search(url)
            assert match is not None, f"{case_id}: {url!r} did not parse"
            assert match.group(1) == slug, f"{case_id}: {url!r} -> {match.group(1)!r}"

    def test_dead_ssh_pattern_is_gone(self) -> None:
        from workspace import WorkspaceManager

        assert not hasattr(WorkspaceManager, "_ORIGIN_SSH_RE")

    def test_non_github_origin_does_not_parse(self) -> None:
        """The pattern stays a GitHub-origin check; it does not match anything."""
        from workspace import WorkspaceManager

        assert (
            WorkspaceManager._ORIGIN_URL_RE.search(
                "https://gitlab.example/owner/repo.git"
            )
            is None
        )
