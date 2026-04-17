"""Regression test for issue #6963.

``sentry_loop._do_work`` iterates project issues without per-issue error
handling.  If Sentry returns a malformed issue object (missing ``"id"`` key,
non-numeric ``"count"``), the exception propagates out of the inner loop
and silently aborts processing of all remaining issues in the project.

These tests will be RED until per-issue ``try/except`` is added around
the inner loop body in ``_do_work``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers (mirrored from test_sentry_loop.py)
# ---------------------------------------------------------------------------


def _make_sentry_issue(
    issue_id: str = "12345",
    title: str = "TypeError: cannot read property 'foo'",
    count: str = "42",
    is_unhandled: bool = True,
) -> dict:
    return {
        "id": issue_id,
        "title": title,
        "culprit": "src/server.py in handle_request",
        "count": count,
        "firstSeen": "2026-03-20T10:00:00Z",
        "lastSeen": "2026-03-27T18:00:00Z",
        "level": "error",
        "permalink": f"https://sentry.io/issues/{issue_id}/",
        "shortId": f"HYDRA-{issue_id}",
        "isUnhandled": is_unhandled,
    }


def _make_loop(config, prs, deps):
    from config import Credentials
    from sentry_loop import SentryLoop

    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    creds = Credentials(sentry_auth_token="sntryu_test")
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


def _make_deps():
    from base_background_loop import LoopDeps

    deps = MagicMock(spec=LoopDeps)
    deps.event_bus = AsyncMock()
    deps.stop_event = MagicMock()
    deps.status_cb = MagicMock()
    deps.enabled_cb = MagicMock(return_value=True)
    deps.sleep_fn = AsyncMock()
    deps.interval_cb = None
    return deps


# ---------------------------------------------------------------------------
# Bug: missing "id" key raises KeyError, aborting the batch
# ---------------------------------------------------------------------------


class TestMalformedIssueMissingId:
    """A Sentry issue missing the ``"id"`` key should be skipped, not raise."""

    @pytest.mark.asyncio
    async def test_missing_id_does_not_raise(self, tmp_path: Path) -> None:
        """_do_work must not raise KeyError when an issue lacks ``"id"``."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        malformed_issue: dict = {"title": "no id field", "count": "5"}

        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[malformed_issue]),
        ):
            # BUG: currently raises KeyError on issue["id"] (line 98)
            result = await loop._do_work()

        assert result is not None

    @pytest.mark.asyncio
    async def test_missing_id_does_not_block_subsequent_issues(
        self, tmp_path: Path
    ) -> None:
        """A malformed issue must not prevent processing of later valid issues."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        malformed_issue: dict = {"title": "no id field", "count": "5"}
        good_issue = _make_sentry_issue(issue_id="99999")

        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(
                loop,
                "_fetch_unresolved",
                return_value=[malformed_issue, good_issue],
            ),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            # BUG: KeyError on the malformed issue prevents good_issue
            # from ever reaching _create_github_issue
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] >= 1
        mock_create.assert_called_once()


# ---------------------------------------------------------------------------
# Bug: non-numeric "count" raises ValueError, aborting the batch
# ---------------------------------------------------------------------------


class TestMalformedIssueNonNumericCount:
    """A Sentry issue with a non-numeric ``"count"`` should be skipped."""

    @pytest.mark.asyncio
    async def test_non_numeric_count_does_not_raise(self, tmp_path: Path) -> None:
        """_do_work must not raise ValueError when count is non-numeric."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)
        object.__setattr__(config, "sentry_min_events", 2)

        bad_count_issue = _make_sentry_issue(count="not-a-number")

        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(loop, "_fetch_unresolved", return_value=[bad_count_issue]),
        ):
            # BUG: int("not-a-number") raises ValueError (line 104)
            result = await loop._do_work()

        assert result is not None

    @pytest.mark.asyncio
    async def test_non_numeric_count_does_not_block_subsequent_issues(
        self, tmp_path: Path
    ) -> None:
        """A bad count on one issue must not block processing of later issues."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)
        object.__setattr__(config, "sentry_min_events", 2)

        bad_count_issue = _make_sentry_issue(issue_id="11111", count="not-a-number")
        good_issue = _make_sentry_issue(issue_id="22222", count="10")

        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "p"}]),
            patch.object(
                loop,
                "_fetch_unresolved",
                return_value=[bad_count_issue, good_issue],
            ),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            # BUG: ValueError on bad_count_issue prevents good_issue
            result = await loop._do_work()

        assert result is not None
        assert result["issues_created"] >= 1
        mock_create.assert_called_once()
