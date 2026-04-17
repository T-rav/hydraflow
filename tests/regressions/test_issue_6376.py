"""Regression test for issue #6376.

Bug: ``SentryLoop._list_projects`` and ``_fetch_unresolved`` call
``raise_for_status()`` with no surrounding try/except.  Any transient
Sentry API failure (5xx, network timeout, token expiry) propagates
uncaught through ``_do_work()`` and crashes the entire poll cycle.

Additionally, a single failing project in ``_fetch_unresolved`` aborts
processing of all remaining projects.

Expected behaviour after fix:
  - Transient httpx errors in ``_list_projects`` are caught and logged
    at ``warning``; ``_do_work`` returns gracefully (e.g., empty project
    list) rather than raising.
  - Transient httpx errors in ``_fetch_unresolved`` for one project do
    not prevent processing of subsequent projects.
  - ``_do_work`` completes without raising on transient API failures.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.helpers import ConfigFactory


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


def _make_loop(config, prs=None, deps=None):
    from config import Credentials
    from sentry_loop import SentryLoop

    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    object.__setattr__(config, "sentry_min_events", 1)
    creds = Credentials(sentry_auth_token="sntryu_test")
    if prs is None:
        prs = MagicMock()
    if deps is None:
        deps = _make_deps()
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


def _http_500_response() -> httpx.Response:
    """Build a fake 500 response that triggers raise_for_status()."""
    request = httpx.Request("GET", "https://sentry.io/api/0/test")
    return httpx.Response(status_code=500, request=request)


class TestListProjectsTransientError:
    """Issue #6376 — _list_projects 5xx must not crash _do_work."""

    @pytest.mark.asyncio
    async def test_list_projects_500_returns_gracefully(
        self, tmp_path: Path
    ) -> None:
        """_do_work should handle a 500 from _list_projects gracefully.

        Currently FAILS: _list_projects raises HTTPStatusError which
        propagates uncaught through _do_work.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        loop = _make_loop(config)

        error_response = _http_500_response()

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(return_value=error_response)

            # DESIRED: _do_work handles the error and returns a result dict
            result = await loop._do_work()
            assert result is not None
            assert result.get("projects_polled", -1) == 0


class TestFetchUnresolvedTransientError:
    """Issue #6376 — _fetch_unresolved 5xx must not crash _do_work."""

    @pytest.mark.asyncio
    async def test_fetch_unresolved_500_returns_gracefully(
        self, tmp_path: Path
    ) -> None:
        """_do_work should handle a 500 from _fetch_unresolved gracefully.

        Currently FAILS: _fetch_unresolved raises HTTPStatusError which
        propagates uncaught through _do_work.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        loop = _make_loop(config)

        ok_response = httpx.Response(
            status_code=200,
            json=[{"slug": "my-project"}],
            request=httpx.Request(
                "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
            ),
        )
        error_response = _http_500_response()

        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return ok_response
            return error_response

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=side_effect)

            # DESIRED: _do_work handles the error and returns a result dict
            result = await loop._do_work()
            assert result is not None
            assert result["projects_polled"] == 1


class TestFetchUnresolvedOneProjectFailure:
    """Issue #6376 — one bad project must not abort remaining projects."""

    @pytest.mark.asyncio
    async def test_bad_project_does_not_skip_remaining(
        self, tmp_path: Path
    ) -> None:
        """When _fetch_unresolved fails for project-a, project-b should
        still be processed.

        Currently FAILS: _do_work raises on project-a's 500 before
        reaching project-b.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        loop = _make_loop(config)

        projects_response = httpx.Response(
            status_code=200,
            json=[{"slug": "project-a"}, {"slug": "project-b"}],
            request=httpx.Request(
                "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
            ),
        )

        project_b_issues_response = httpx.Response(
            status_code=200,
            json=[],  # no issues — just prove we reached this project
            request=httpx.Request(
                "GET",
                "https://sentry.io/api/0/projects/test-org/project-b/issues/",
            ),
        )

        error_response = _http_500_response()
        call_count = 0

        async def side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return projects_response  # _list_projects
            if call_count == 2:
                return error_response  # _fetch_unresolved for project-a (500)
            return project_b_issues_response  # _fetch_unresolved for project-b

        with patch("httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client_cls.return_value.__aenter__ = AsyncMock(
                return_value=mock_client
            )
            mock_client_cls.return_value.__aexit__ = AsyncMock(return_value=False)
            mock_client.get = AsyncMock(side_effect=side_effect)

            # DESIRED: _do_work continues past project-a and processes project-b
            result = await loop._do_work()
            assert result is not None
            assert result["projects_polled"] == 2
            # We should have reached the third httpx call (project-b)
            assert call_count == 3
