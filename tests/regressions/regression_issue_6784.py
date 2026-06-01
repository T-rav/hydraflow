"""Regression test for issue #6784.

Bug 1: ``pr_manager.py:714`` — ``list_issues_by_label`` catches ``Exception``,
logs at WARNING, then re-raises via bare ``raise``.  Every caller
(``diagnostic_loop``, ``stale_issue_gc_loop``, ``ci_monitor_loop``) also
catches ``Exception`` and logs at WARNING — producing duplicate WARNING
entries for the same error.  Compare with ``get_issue_state:677`` which
swallows the exception and returns ``"UNKNOWN"`` — no double-logging.

Bug 2: ``github_cache_loop.py:208`` — ``_save_to_disk`` catches **all**
exceptions at ``DEBUG`` level.  When ``mkdir`` or ``write_text`` fail due to
an ``OSError`` (disk full, bad permissions), the error is invisible in
production logs.  Serious disk errors should surface at ``WARNING``.

These tests assert the CORRECT (post-fix) behaviour and are therefore RED
against the current buggy code.
"""

from __future__ import annotations

import logging
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from events import EventBus
from github_cache_loop import CacheSnapshot, GitHubDataCache
from pr_manager import PRManager
from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_pr_manager() -> PRManager:
    """Build a PRManager with a valid repo slug so _assert_repo passes."""
    config = ConfigFactory.create(repo="test-owner/test-repo")
    bus = MagicMock(spec=EventBus)
    bus.emit = AsyncMock()
    return PRManager(config, bus)


def _make_cache(tmp_path: Path) -> GitHubDataCache:
    """Build a GitHubDataCache with a controlled cache directory."""
    config = ConfigFactory.create(repo="test-owner/test-repo")
    pr_manager = MagicMock()
    fetcher = MagicMock()
    return GitHubDataCache(config, pr_manager, fetcher, cache_dir=tmp_path)


# ---------------------------------------------------------------------------
# Bug 1 — double-logging in list_issues_by_label
# ---------------------------------------------------------------------------


class TestListIssuesByLabelDoubleLogging:
    """Issue #6784 — ``list_issues_by_label`` should NOT log at WARNING
    when it re-raises the exception.  The caller is responsible for logging.

    Currently FAILS (RED) because the method at line 714-716 both logs at
    WARNING *and* re-raises, causing every caller to produce a second
    WARNING for the same error.

    Expected post-fix behaviour: either remove the ``raise`` and return
    ``[]`` on failure (like ``get_issue_state`` returns ``"UNKNOWN"``),
    or remove the ``logger.warning`` so only the caller logs.
    """

    @pytest.mark.asyncio
    async def test_no_warning_logged_when_exception_propagates(
        self, caplog: pytest.LogCaptureFixture
    ) -> None:
        """If list_issues_by_label re-raises, it must not also log WARNING.

        We trigger a RuntimeError from _run_gh and capture log records.
        The method should either:
          (a) swallow the exception, return [], and log WARNING once, or
          (b) re-raise without logging (let the caller decide).

        The bug is that it does BOTH: logs WARNING *and* re-raises.
        """
        pm = _make_pr_manager()

        with (
            patch.object(pm, "_run_gh", side_effect=RuntimeError("gh: network error")),
            caplog.at_level(logging.WARNING, logger="hydraflow.pr_manager"),
        ):
            raised = False
            try:
                await pm.list_issues_by_label("hydraflow-ready")
            except RuntimeError:
                raised = True

            # Count WARNING records from pr_manager about this failure
            warning_records = [
                r
                for r in caplog.records
                if r.levelno == logging.WARNING and "list issues" in r.message.lower()
            ]

            if raised:
                # Method re-raised → it must NOT have logged (caller will log)
                assert len(warning_records) == 0, (
                    f"list_issues_by_label logged {len(warning_records)} WARNING(s) "
                    f"AND re-raised the exception — this causes double-logging. "
                    f"Either swallow the exception or remove the log."
                )
            else:
                # Method swallowed → it must have logged exactly once
                assert len(warning_records) == 1, (
                    f"list_issues_by_label swallowed the exception but logged "
                    f"{len(warning_records)} WARNING(s) — expected exactly 1."
                )


# ---------------------------------------------------------------------------
# Bug 2 — _save_to_disk swallows OSError at DEBUG
# ---------------------------------------------------------------------------


class TestSaveToDiskOSErrorLogging:
    """Issue #6784 — ``_save_to_disk`` should log at WARNING when an
    ``OSError`` prevents cache persistence.

    Currently FAILS (RED) because the ``except Exception`` block at
    line 208 logs unconditionally at ``DEBUG`` — serious disk errors
    (permissions denied, disk full) are invisible in production logs
    where DEBUG is typically suppressed.
    """

    @pytest.mark.xfail(reason="Regression for issue #6784 — fix not yet landed", strict=False)
    def test_oserror_logged_at_warning(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """When write_text raises OSError, a WARNING is emitted.

        We construct the cache normally (writable dir), then make the
        cache directory read-only before calling _save_to_disk so that
        write_text fails with PermissionError (an OSError subclass).
        """
        cache = _make_cache(tmp_path)
        # Pre-populate some data so _save_to_disk has something to write
        cache._open_prs = CacheSnapshot(data=[])

        # Make the cache directory read-only so write_text fails
        tmp_path.chmod(0o444)

        try:
            with caplog.at_level(logging.DEBUG, logger="hydraflow.github_cache"):
                cache._save_to_disk()

            # Collect records about cache persistence failure
            cache_fail_records = [
                r
                for r in caplog.records
                if "persist" in r.message.lower() or "cache" in r.message.lower()
            ]

            # There should be at least one record at WARNING or higher for OSError
            warning_or_above = [
                r for r in cache_fail_records if r.levelno >= logging.WARNING
            ]
            assert len(warning_or_above) >= 1, (
                f"OSError during _save_to_disk was only logged at DEBUG level. "
                f"Got {len(cache_fail_records)} record(s) total, "
                f"but {len(warning_or_above)} at WARNING+. "
                f"Disk errors should surface at WARNING so operators notice them."
            )
        finally:
            tmp_path.chmod(0o755)

    def test_non_os_error_stays_at_debug(
        self, tmp_path: Path, caplog: pytest.LogCaptureFixture
    ) -> None:
        """Non-OSError exceptions (e.g. JSON serialization) can stay DEBUG.

        This test ensures the fix is targeted: only OSError gets escalated.
        We inject a non-serializable object to trigger a TypeError in json.dumps.
        """
        cache = _make_cache(tmp_path)
        # Inject a non-serializable object so json.dumps raises TypeError
        cache._open_prs = CacheSnapshot(data=[object()])

        with caplog.at_level(logging.DEBUG, logger="hydraflow.github_cache"):
            cache._save_to_disk()

        cache_fail_records = [
            r
            for r in caplog.records
            if "persist" in r.message.lower() or "cache" in r.message.lower()
        ]

        # Non-OSError should NOT be at WARNING — DEBUG is fine
        warning_records = [
            r for r in cache_fail_records if r.levelno >= logging.WARNING
        ]
        assert len(warning_records) == 0, (
            "Non-OSError exception during _save_to_disk was logged at WARNING. "
            "Only OSError should be escalated to WARNING."
        )
