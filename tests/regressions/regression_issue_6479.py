"""Regression test for issue #6479.

Bug: ``sentry_loop.SentryLoop._list_projects()`` and ``_fetch_unresolved()``
call ``resp.raise_for_status()`` without a surrounding ``try/except``.  When
Sentry returns a 401 or 403 (e.g. invalid ``SENTRY_AUTH_TOKEN``), an
``httpx.HTTPStatusError`` propagates uncaught out of ``_do_work()``.

Because ``HTTPStatusError`` is not in ``LIKELY_BUG_EXCEPTIONS`` and is not an
``AuthenticationError``/``CreditExhaustedError``, it reaches the base loop's
generic handler which logs-and-continues — retrying every poll cycle with no
backoff.  The result is repeated Sentry API calls with invalid credentials,
potential rate-limiting, and noisy logs with no actionable message.

Expected behaviour after fix:
  - ``_do_work()`` catches ``httpx.HTTPStatusError`` for 401/403 responses
    and returns a result dict (does NOT let the exception propagate).
  - A specific warning is logged mentioning ``SENTRY_AUTH_TOKEN``.
  - The loop backs off on auth failures instead of retrying every cycle.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from tests.helpers import ConfigFactory

# ---------------------------------------------------------------------------
# Helpers
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
    creds = Credentials(sentry_auth_token="sntryu_bad_token")
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


def _mock_401_response() -> httpx.Response:
    """Build a realistic 401 response that raise_for_status() will reject."""
    request = httpx.Request(
        "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
    )
    resp = httpx.Response(
        status_code=401, request=request, json={"detail": "Invalid token"}
    )
    return resp


def _mock_403_response() -> httpx.Response:
    """Build a realistic 403 response."""
    request = httpx.Request(
        "GET", "https://sentry.io/api/0/organizations/test-org/projects/"
    )
    resp = httpx.Response(
        status_code=403, request=request, json={"detail": "Forbidden"}
    )
    return resp


# ---------------------------------------------------------------------------
# Tests — _list_projects 401/403 must not propagate
# ---------------------------------------------------------------------------


class TestListProjects401DoesNotPropagate:
    """A 401 from Sentry in _list_projects must be caught, not propagated.

    Current (buggy) behaviour: ``httpx.HTTPStatusError`` propagates out of
    ``_do_work()``.

    Expected (fixed) behaviour: ``_do_work()`` catches the error and returns
    a result dict indicating the auth failure.
    """

    @pytest.mark.asyncio
    async def test_list_projects_401_does_not_raise(self, tmp_path: Path) -> None:
        """_do_work() must not raise when _list_projects gets a 401."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        mock_resp = _mock_401_response()

        with patch("sentry_loop.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            # BUG: This raises httpx.HTTPStatusError instead of handling it.
            # After fix, _do_work() should return a dict, not raise.
            result = await loop._do_work()

        assert result is not None, "_do_work() must return a result, not raise"

    @pytest.mark.asyncio
    async def test_list_projects_403_does_not_raise(self, tmp_path: Path) -> None:
        """_do_work() must not raise when _list_projects gets a 403."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        mock_resp = _mock_403_response()

        with patch("sentry_loop.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            result = await loop._do_work()

        assert result is not None, "_do_work() must return a result, not raise"


# ---------------------------------------------------------------------------
# Tests — _fetch_unresolved 401 must not propagate
# ---------------------------------------------------------------------------


class TestFetchUnresolved401DoesNotPropagate:
    """A 401 from Sentry in _fetch_unresolved must be caught, not propagated."""

    @pytest.mark.asyncio
    async def test_fetch_unresolved_401_does_not_raise(self, tmp_path: Path) -> None:
        """_do_work() must not raise when _fetch_unresolved gets a 401."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        mock_resp_401 = _mock_401_response()

        # _list_projects succeeds, but _fetch_unresolved gets 401
        with (
            patch.object(loop, "_list_projects", return_value=[{"slug": "myproject"}]),
            patch("sentry_loop.httpx.AsyncClient") as mock_client_cls,
        ):
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(return_value=mock_resp_401)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            # BUG: This raises httpx.HTTPStatusError from _fetch_unresolved.
            result = await loop._do_work()

        assert result is not None, "_do_work() must return a result, not raise"


# ---------------------------------------------------------------------------
# Tests — repeated 401s should not cause repeated API calls (backoff)
# ---------------------------------------------------------------------------


class TestSentryAuthErrorBackoff:
    """After a Sentry 401/403, the loop should back off instead of retrying
    every poll cycle with the same bad credentials.

    Current (buggy) behaviour: the exception propagates, the base loop
    catches it, and the next cycle retries immediately — no backoff.

    Expected (fixed) behaviour: _do_work() records the auth failure and
    subsequent calls within the backoff window skip the Sentry API call.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6479 — fix not yet landed", strict=False)
    async def test_second_call_after_401_skips_api(self, tmp_path: Path) -> None:
        """After a 401, the next _do_work() should skip the API call (backoff)."""
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        mock_resp_401 = _mock_401_response()
        call_count = 0

        async def counting_get(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            return mock_resp_401

        with patch("sentry_loop.httpx.AsyncClient") as mock_client_cls:
            mock_client = AsyncMock()
            mock_client.get = AsyncMock(side_effect=counting_get)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            # First call — hits the API, gets 401
            try:
                await loop._do_work()
            except httpx.HTTPStatusError:
                pass  # current buggy behaviour raises

            # Second call — should NOT hit the API again (backoff)
            try:
                await loop._do_work()
            except httpx.HTTPStatusError:
                pass  # current buggy behaviour raises again

        # BUG: Both calls hit the API. After fix, only the first should.
        assert call_count <= 1, (
            f"Expected at most 1 Sentry API call (backoff after 401), "
            f"but got {call_count}"
        )


# ---------------------------------------------------------------------------
# Tests — _resolve_sentry_issue 401 is silently swallowed
# ---------------------------------------------------------------------------


class TestResolveSentryIssue401NotSwallowed:
    """A 401 from Sentry in _resolve_sentry_issue is currently swallowed by
    the generic ``except Exception`` handler (line 207).  The
    ``reraise_on_credit_or_bug`` call does not re-raise HTTPStatusError for
    401, so the error is logged as a generic warning with no mention of bad
    credentials.

    Expected (fixed) behaviour: 401/403 from _resolve_sentry_issue should
    log a specific warning mentioning SENTRY_AUTH_TOKEN.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6479 — fix not yet landed", strict=False)
    async def test_resolve_401_logs_auth_warning(self, tmp_path: Path) -> None:
        """A 401 in _resolve_sentry_issue should log a message mentioning
        SENTRY_AUTH_TOKEN, not just a generic 'Failed to resolve' warning.
        """
        config = ConfigFactory.create(repo_root=tmp_path)
        deps = _make_deps()
        prs = MagicMock()

        loop = _make_loop(config, prs, deps)

        mock_resp_401 = httpx.Response(
            status_code=401,
            request=httpx.Request("PUT", "https://sentry.io/api/0/issues/12345/"),
            json={"detail": "Invalid token"},
        )

        with (
            patch("sentry_loop.httpx.AsyncClient") as mock_client_cls,
            patch("sentry_loop.logger") as mock_logger,
        ):
            mock_client = AsyncMock()
            mock_client.put = AsyncMock(return_value=mock_resp_401)
            mock_ctx = AsyncMock()
            mock_ctx.__aenter__ = AsyncMock(return_value=mock_client)
            mock_ctx.__aexit__ = AsyncMock(return_value=False)
            mock_client_cls.return_value = mock_ctx

            await loop._resolve_sentry_issue("12345")

        # Check that the warning mentions SENTRY_AUTH_TOKEN
        warning_calls = mock_logger.warning.call_args_list
        assert len(warning_calls) > 0, "Expected a warning to be logged"
        warning_message = str(warning_calls[0])
        assert "SENTRY_AUTH_TOKEN" in warning_message, (
            f"Warning should mention SENTRY_AUTH_TOKEN for actionable guidance, "
            f"but got: {warning_message}"
        )
