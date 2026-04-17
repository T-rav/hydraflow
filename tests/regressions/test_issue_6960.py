"""Regression test for issue #6960.

``SentryLoop._do_work`` calls ``_list_projects()`` and ``_fetch_unresolved()``
without any try/except.  Both methods call ``resp.raise_for_status()`` which
raises ``httpx.HTTPStatusError`` on non-2xx responses, and the HTTP client can
also raise ``httpx.ConnectError`` / ``httpx.TimeoutException`` on network
failures.

Because neither call site catches these exceptions:

1. A network error in ``_list_projects`` crashes the entire ingestion cycle —
   no projects are processed at all.
2. A failure in ``_fetch_unresolved`` for one project aborts the loop, skipping
   all remaining projects even though they may be healthy.

These tests exercise both failure modes and will be RED until proper
per-project error handling is added to ``_do_work``.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers (mirrors test_sentry_loop.py conventions)
# ---------------------------------------------------------------------------


def _make_sentry_issue(issue_id: str = "12345", count: str = "42") -> dict:
    return {
        "id": issue_id,
        "title": "TypeError: cannot read property 'foo'",
        "culprit": "src/server.py in handle_request",
        "count": count,
        "firstSeen": "2026-03-20T10:00:00Z",
        "lastSeen": "2026-03-27T18:00:00Z",
        "level": "error",
        "permalink": f"https://sentry.io/issues/{issue_id}/",
        "shortId": f"HYDRA-{issue_id}",
        "isUnhandled": True,
    }


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


def _make_loop(config, prs, deps):
    from config import Credentials
    from sentry_loop import SentryLoop

    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    creds = Credentials(sentry_auth_token="sntryu_test")
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


# ---------------------------------------------------------------------------
# Bug 1: _list_projects HTTP error crashes the entire ingestion cycle
# ---------------------------------------------------------------------------


class TestListProjectsErrorHandling:
    """_list_projects raises httpx errors that propagate unhandled from _do_work."""

    @pytest.mark.asyncio
    async def test_list_projects_http_500_does_not_crash_do_work(
        self, tmp_path: Path
    ) -> None:
        """When the Sentry API returns 500 for the project list, _do_work should
        catch the error and return gracefully (e.g. empty metrics), not propagate
        the HTTPStatusError.

        Currently the exception escapes _do_work — this test is RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        # Simulate _list_projects raising HTTPStatusError (from raise_for_status)
        mock_request = httpx.Request(
            "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
        )
        mock_response = httpx.Response(500, request=mock_request)
        error = httpx.HTTPStatusError(
            "Server Error", request=mock_request, response=mock_response
        )
        with patch.object(loop, "_list_projects", side_effect=error):
            # Bug: this raises httpx.HTTPStatusError instead of returning gracefully
            result = await loop._do_work()

        assert result is not None, (
            "_do_work must return a result dict, not propagate HTTPStatusError "
            "from _list_projects (issue #6960)"
        )

    @pytest.mark.asyncio
    async def test_list_projects_connect_error_does_not_crash_do_work(
        self, tmp_path: Path
    ) -> None:
        """When the Sentry API is unreachable, _do_work should handle
        the connection error gracefully.

        Currently the exception escapes _do_work — this test is RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        error = httpx.ConnectError("Connection refused")
        with patch.object(loop, "_list_projects", side_effect=error):
            result = await loop._do_work()

        assert result is not None, (
            "_do_work must return a result dict, not propagate ConnectError "
            "from _list_projects (issue #6960)"
        )


# ---------------------------------------------------------------------------
# Bug 2: _fetch_unresolved failure on one project skips all remaining projects
# ---------------------------------------------------------------------------


class TestFetchUnresolvedPerProjectIsolation:
    """_fetch_unresolved failure for one project must not abort the whole loop."""

    @pytest.mark.asyncio
    async def test_one_project_failure_does_not_skip_remaining(
        self, tmp_path: Path
    ) -> None:
        """With 3 projects, if _fetch_unresolved fails on the 2nd project,
        the 1st and 3rd projects should still be processed normally.

        Currently the exception from project-b aborts the loop and project-c
        is never reached — this test is RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        loop = _make_loop(config, prs, deps)

        projects = [
            {"slug": "project-a"},
            {"slug": "project-b"},
            {"slug": "project-c"},
        ]

        issue_a = _make_sentry_issue(issue_id="1001")
        issue_c = _make_sentry_issue(issue_id="1003")

        mock_request = httpx.Request(
            "GET",
            "https://sentry.io/api/0/projects/test-org/project-b/issues/",
        )
        mock_response = httpx.Response(500, request=mock_request)
        fetch_error = httpx.HTTPStatusError(
            "Server Error", request=mock_request, response=mock_response
        )

        async def _fetch_side_effect(slug: str):
            if slug == "project-b":
                raise fetch_error
            if slug == "project-a":
                return [issue_a]
            if slug == "project-c":
                return [issue_c]
            return []

        with (
            patch.object(loop, "_list_projects", return_value=projects),
            patch.object(loop, "_fetch_unresolved", side_effect=_fetch_side_effect),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None, (
            "_do_work must not crash when _fetch_unresolved fails for one project "
            "(issue #6960)"
        )
        # project-a and project-c issues should both be created
        assert mock_create.call_count == 2, (
            f"Expected 2 issues created (project-a + project-c), got "
            f"{mock_create.call_count} — project-b failure aborted remaining "
            f"projects (issue #6960)"
        )
        assert result["issues_created"] == 2

    @pytest.mark.asyncio
    async def test_timeout_on_one_project_still_processes_others(
        self, tmp_path: Path
    ) -> None:
        """A timeout fetching one project's issues must not block the others.

        Currently the httpx.ReadTimeout escapes the per-project loop — RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        loop = _make_loop(config, prs, deps)

        projects = [
            {"slug": "healthy-project"},
            {"slug": "slow-project"},
        ]

        healthy_issue = _make_sentry_issue(issue_id="2001")

        async def _fetch_side_effect(slug: str):
            if slug == "slow-project":
                raise httpx.ReadTimeout("Read timed out")
            return [healthy_issue]

        with (
            patch.object(loop, "_list_projects", return_value=projects),
            patch.object(loop, "_fetch_unresolved", side_effect=_fetch_side_effect),
            patch.object(
                loop, "_create_github_issue", return_value=True
            ) as mock_create,
            patch.object(loop, "_resolve_sentry_issue", new_callable=AsyncMock),
        ):
            result = await loop._do_work()

        assert result is not None, (
            "_do_work crashed due to ReadTimeout on slow-project (issue #6960)"
        )
        assert mock_create.call_count == 1, (
            f"Expected 1 issue from healthy-project, got {mock_create.call_count} — "
            f"slow-project timeout aborted the loop (issue #6960)"
        )


# ---------------------------------------------------------------------------
# Bug 3: _list_projects and _fetch_unresolved raise_for_status is uncaught
# ---------------------------------------------------------------------------


class TestRawHttpMethodErrorHandling:
    """The actual _list_projects and _fetch_unresolved methods call
    raise_for_status() without any try/except, so HTTP errors propagate
    directly to _do_work (which also has no handler)."""

    @pytest.mark.asyncio
    async def test_list_projects_returns_empty_on_http_error(
        self, tmp_path: Path
    ) -> None:
        """_list_projects should catch HTTP errors and return an empty list
        rather than letting raise_for_status propagate.

        Currently raise_for_status is uncaught — this test is RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        mock_request = httpx.Request(
            "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
        )
        mock_response = httpx.Response(502, request=mock_request)

        with patch("sentry_loop.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Bad Gateway", request=mock_request, response=mock_response
            )
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_resp))
            )
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            # Bug: this raises httpx.HTTPStatusError
            try:
                result = await loop._list_projects()
            except httpx.HTTPStatusError:
                pytest.fail(
                    "_list_projects must catch HTTPStatusError from "
                    "raise_for_status and return [] (issue #6960)"
                )

        assert result == [], "_list_projects should return empty list on HTTP error"

    @pytest.mark.asyncio
    async def test_fetch_unresolved_returns_empty_on_http_error(
        self, tmp_path: Path
    ) -> None:
        """_fetch_unresolved should catch HTTP errors and return an empty list.

        Currently raise_for_status is uncaught — this test is RED.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        mock_request = httpx.Request(
            "GET", "https://sentry.io/api/0/projects/test-org/myproject/issues/"
        )
        mock_response = httpx.Response(503, request=mock_request)

        with patch("sentry_loop.httpx.AsyncClient") as mock_client_cls:
            mock_resp = MagicMock()
            mock_resp.raise_for_status.side_effect = httpx.HTTPStatusError(
                "Service Unavailable", request=mock_request, response=mock_response
            )
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(
                return_value=MagicMock(get=AsyncMock(return_value=mock_resp))
            )
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            # Bug: this raises httpx.HTTPStatusError
            try:
                result = await loop._fetch_unresolved("myproject")
            except httpx.HTTPStatusError:
                pytest.fail(
                    "_fetch_unresolved must catch HTTPStatusError from "
                    "raise_for_status and return [] (issue #6960)"
                )

        assert result == [], "_fetch_unresolved should return empty list on HTTP error"
