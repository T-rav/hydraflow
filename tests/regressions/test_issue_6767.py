"""Regression test for issue #6767.

Bug: ``SentryLoop._list_projects()`` and ``_fetch_unresolved()`` call
``httpx.AsyncClient.get()`` and ``resp.raise_for_status()`` with no
surrounding ``try/except``.  Any ``httpx.ConnectError``,
``httpx.TimeoutException``, or non-2xx Sentry API response propagates
unhandled out of ``_do_work()``, aborting the entire poll cycle.

Contrast with ``_resolve_sentry_issue()`` and ``_fetch_latest_event()``
which correctly wrap their HTTP calls in ``try/except``.

Expected behaviour after fix:
  - ``_list_projects`` catches ``httpx.HTTPError`` (and subclasses like
    ``ConnectError``, ``TimeoutException``), logs a warning, and returns
    an empty list so the cycle completes gracefully.
  - ``_fetch_unresolved`` catches the same errors and returns an empty
    list so other projects in the cycle are still processed.

These tests assert the *correct* behaviour and are RED against the
current (buggy) code.
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
# Helpers (same factory pattern as test_sentry_loop.py)
# ---------------------------------------------------------------------------


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


def _mock_httpx_client_raising(exc: Exception):
    """Return a context-manager mock for ``httpx.AsyncClient`` that raises *exc* on ``.get()``."""
    mock_client = AsyncMock()
    mock_client.get = AsyncMock(side_effect=exc)
    mock_ctx = AsyncMock()
    mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
    mock_ctx.__aexit__ = AsyncMock(return_value=False)
    return mock_ctx


# ---------------------------------------------------------------------------
# Tests for _list_projects error handling
# ---------------------------------------------------------------------------


class TestListProjectsErrorHandling:
    """_list_projects should catch transient httpx errors, not propagate them."""

    @pytest.mark.asyncio
    async def test_connect_error_returns_empty_list(self, tmp_path: Path) -> None:
        """A ConnectError (e.g., DNS failure) should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        exc = httpx.ConnectError("Failed to resolve hostname")
        with patch(
            "sentry_loop.httpx.AsyncClient",
            return_value=_mock_httpx_client_raising(exc),
        ):
            result = await loop._list_projects()

        assert result == [], (
            "_list_projects should return [] on ConnectError, not propagate the exception"
        )

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_list(self, tmp_path: Path) -> None:
        """A TimeoutException should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        exc = httpx.ReadTimeout("Read timed out")
        with patch(
            "sentry_loop.httpx.AsyncClient",
            return_value=_mock_httpx_client_raising(exc),
        ):
            result = await loop._list_projects()

        assert result == [], (
            "_list_projects should return [] on ReadTimeout, not propagate the exception"
        )

    @pytest.mark.asyncio
    async def test_http_503_returns_empty_list(self, tmp_path: Path) -> None:
        """A 503 from Sentry should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        # Simulate raise_for_status() raising HTTPStatusError for a 503
        mock_request = httpx.Request(
            "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
        )
        mock_response = httpx.Response(503, request=mock_request)
        exc = httpx.HTTPStatusError(
            "Server Error", request=mock_request, response=mock_response
        )

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=exc)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("sentry_loop.httpx.AsyncClient", return_value=mock_ctx):
            result = await loop._list_projects()

        assert result == [], (
            "_list_projects should return [] on HTTP 503, not propagate the exception"
        )


# ---------------------------------------------------------------------------
# Tests for _fetch_unresolved error handling
# ---------------------------------------------------------------------------


class TestFetchUnresolvedErrorHandling:
    """_fetch_unresolved should catch transient httpx errors, not propagate them."""

    @pytest.mark.asyncio
    async def test_connect_error_returns_empty_list(self, tmp_path: Path) -> None:
        """A ConnectError should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        exc = httpx.ConnectError("Connection refused")
        with patch(
            "sentry_loop.httpx.AsyncClient",
            return_value=_mock_httpx_client_raising(exc),
        ):
            result = await loop._fetch_unresolved("my-project")

        assert result == [], (
            "_fetch_unresolved should return [] on ConnectError, not propagate the exception"
        )

    @pytest.mark.asyncio
    async def test_timeout_returns_empty_list(self, tmp_path: Path) -> None:
        """A TimeoutException should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        exc = httpx.ReadTimeout("Read timed out")
        with patch(
            "sentry_loop.httpx.AsyncClient",
            return_value=_mock_httpx_client_raising(exc),
        ):
            result = await loop._fetch_unresolved("my-project")

        assert result == [], (
            "_fetch_unresolved should return [] on ReadTimeout, not propagate the exception"
        )

    @pytest.mark.asyncio
    async def test_http_503_returns_empty_list(self, tmp_path: Path) -> None:
        """A 503 from Sentry should be caught and return []."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        mock_request = httpx.Request(
            "GET", "https://sentry.io/api/0/projects/test-org/my-project/issues/"
        )
        mock_response = httpx.Response(503, request=mock_request)
        exc = httpx.HTTPStatusError(
            "Server Error", request=mock_request, response=mock_response
        )

        mock_client = AsyncMock()
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock(side_effect=exc)
        mock_client.get = AsyncMock(return_value=mock_resp)
        mock_ctx = AsyncMock()
        mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
        mock_ctx.__aexit__ = AsyncMock(return_value=False)

        with patch("sentry_loop.httpx.AsyncClient", return_value=mock_ctx):
            result = await loop._fetch_unresolved("my-project")

        assert result == [], (
            "_fetch_unresolved should return [] on HTTP 503, not propagate the exception"
        )


# ---------------------------------------------------------------------------
# Tests for _do_work cycle resilience
# ---------------------------------------------------------------------------


class TestDoWorkCycleResilience:
    """_do_work should complete gracefully when API calls fail transiently."""

    @pytest.mark.asyncio
    async def test_list_projects_failure_does_not_crash_cycle(
        self, tmp_path: Path
    ) -> None:
        """If _list_projects hits a network error, _do_work should return
        a result dict (not raise), so the loop retries next interval."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        loop = _make_loop(config, prs, deps)

        exc = httpx.ConnectError("DNS resolution failed")
        with patch(
            "sentry_loop.httpx.AsyncClient",
            return_value=_mock_httpx_client_raising(exc),
        ):
            # Should NOT raise — should return a result with 0 projects
            result = await loop._do_work()

        assert result is not None, "_do_work should return a result, not raise"
        assert result["projects_polled"] == 0

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6767 — fix not yet landed", strict=False)
    async def test_fetch_unresolved_failure_still_processes_other_projects(
        self, tmp_path: Path
    ) -> None:
        """If _fetch_unresolved fails for one project, other projects
        should still be processed."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()
        prs._run_gh = AsyncMock(return_value="0")
        loop = _make_loop(config, prs, deps)

        call_count = 0

        async def _fetch_side_effect(slug: str) -> list:
            nonlocal call_count
            call_count += 1
            if slug == "project-a":
                raise httpx.ConnectError("Connection refused")
            return []  # project-b succeeds with no issues

        with (
            patch.object(
                loop,
                "_list_projects",
                return_value=[{"slug": "project-a"}, {"slug": "project-b"}],
            ),
            patch.object(
                loop,
                "_fetch_unresolved",
                side_effect=_fetch_side_effect,
            ),
        ):
            # Should NOT raise — project-b should still be processed
            result = await loop._do_work()

        assert result is not None, (
            "_do_work should not crash when _fetch_unresolved fails for one project"
        )
        assert call_count == 2, (
            "_fetch_unresolved should be called for both projects, even if the first fails"
        )
