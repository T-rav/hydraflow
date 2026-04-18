"""Regression test for issue #6923.

Bug: PRManager.create_pr parses the PR number from the gh CLI output URL via
``int(pr_url.rstrip("/").split("/")[-1])``.  The ``/pull/`` presence check
guards against completely unexpected formats, but URLs like:

  - ``https://github.com/org/repo/pull/``       (trailing slash only)
  - ``https://github.com/org/repo/pull/draft``   (non-numeric segment)

pass the guard and cause ``int()`` to raise a bare ``ValueError`` with no URL
context.  The except block on line 310 catches both ``RuntimeError`` and
``ValueError``, so the process doesn't crash — but the error logged is a
generic ``ValueError`` instead of a ``RuntimeError`` that includes the
offending URL for diagnosis.

Expected behaviour after fix:
  - The ``int()`` parse failure is caught locally and re-raised as
    ``RuntimeError(f"Could not parse PR number from URL: {pr_url}")``
  - The logged error includes the malformed URL for debugging

These tests assert the *correct* behaviour, so they are RED against the
current (buggy) code.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.conftest import SubprocessMockBuilder
from tests.helpers import ConfigFactory, make_pr_manager


@pytest.fixture()
def config(tmp_path: Path):
    return ConfigFactory.create(
        repo_root=tmp_path / "repo",
        workspace_base=tmp_path / "worktrees",
        state_file=tmp_path / "state.json",
    )


@pytest.fixture()
def event_bus():
    from events import EventBus

    return EventBus()


@pytest.fixture()
def issue():
    from tests.conftest import IssueFactory

    return IssueFactory.create()


class TestCreatePrMalformedUrlRaisesRuntimeError:
    """Issue #6923 — non-numeric PR URL segment should raise RuntimeError with URL context."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6923 — fix not yet landed", strict=False)
    async def test_trailing_slash_only_logs_runtime_error(
        self, config, event_bus, issue, caplog
    ) -> None:
        """URL ``https://…/pull/`` (trailing slash, empty segment after strip)
        should produce a RuntimeError mentioning the URL, not a bare ValueError."""
        manager = make_pr_manager(config, event_bus)
        malformed_url = "https://github.com/org/repo/pull/"
        mock_create = SubprocessMockBuilder().with_stdout(malformed_url).build()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            caplog.at_level(logging.ERROR, logger="hydraflow.pr_manager"),
        ):
            result = await manager.create_pr(issue, "agent/issue-42")

        # The fallback path returns PRInfo with number=0 regardless of
        # exception type, so we must inspect the logged error to distinguish.
        assert result.number == 0, "Expected fallback PRInfo with number=0"

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "Expected an error log from create_pr"

        logged_exc = error_records[0].args[-1] if error_records[0].args else None
        # The logged message format is: "PR creation failed for issue #%d: %s"
        # where %s is the exception.  After the fix the exc should be RuntimeError.
        logged_message = error_records[0].getMessage()

        assert (
            "RuntimeError" in type(logged_exc).__name__
            or "Could not parse PR number" in logged_message
        ), (
            f"Expected RuntimeError with URL context, got: {logged_message!r} — "
            "this is the ValueError-without-context bug from issue #6923"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6923 — fix not yet landed", strict=False)
    async def test_non_numeric_segment_logs_runtime_error(
        self, config, event_bus, issue, caplog
    ) -> None:
        """URL ``https://…/pull/draft`` should produce a RuntimeError
        mentioning the URL, not a bare ValueError."""
        manager = make_pr_manager(config, event_bus)
        malformed_url = "https://github.com/org/repo/pull/draft"
        mock_create = SubprocessMockBuilder().with_stdout(malformed_url).build()

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            caplog.at_level(logging.ERROR, logger="hydraflow.pr_manager"),
        ):
            result = await manager.create_pr(issue, "agent/issue-42")

        assert result.number == 0, "Expected fallback PRInfo with number=0"

        error_records = [r for r in caplog.records if r.levelno >= logging.ERROR]
        assert error_records, "Expected an error log from create_pr"

        logged_message = error_records[0].getMessage()

        # After the fix, the error message should contain the malformed URL
        # and be a RuntimeError, not the bare ValueError from int().
        assert malformed_url in logged_message, (
            f"Expected malformed URL in error message, got: {logged_message!r} — "
            "this is the ValueError-without-context bug from issue #6923"
        )

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6923 — fix not yet landed", strict=False)
    async def test_non_numeric_segment_exception_is_runtime_error(
        self, config, event_bus, issue
    ) -> None:
        """The exception raised internally must be RuntimeError, not ValueError.

        We verify this by patching find_open_pr_for_branch (called in the
        except handler) and inspecting the exception that was active when
        the handler ran.
        """
        manager = make_pr_manager(config, event_bus)
        malformed_url = "https://github.com/org/repo/pull/draft"
        mock_create = SubprocessMockBuilder().with_stdout(malformed_url).build()

        captured_exceptions: list[BaseException] = []

        original_find = manager.find_open_pr_for_branch

        async def spy_find(*args, **kwargs):
            """Capture the exception context when the fallback handler runs."""
            import sys as _sys

            exc_info = _sys.exc_info()
            if exc_info[1] is not None:
                captured_exceptions.append(exc_info[1])
            return await original_find(*args, **kwargs)

        with (
            patch("asyncio.create_subprocess_exec", mock_create),
            patch.object(manager, "find_open_pr_for_branch", side_effect=spy_find),
        ):
            result = await manager.create_pr(issue, "agent/issue-42")

        assert result.number == 0

        assert captured_exceptions, "Expected an exception to be caught in the handler"
        exc = captured_exceptions[0]
        assert isinstance(exc, RuntimeError), (
            f"Expected RuntimeError but got {type(exc).__name__}: {exc} — "
            "this is the ValueError-without-context bug from issue #6923"
        )
        assert malformed_url[:50] in str(exc), (
            f"Expected URL context in exception message, got: {exc!r}"
        )
