"""Regression test for issue #6656.

Bug: ``SentryLoop._list_projects()``, ``_fetch_unresolved()``, and
``_fetch_latest_event()`` call ``resp.json()`` after ``raise_for_status()``
with no guard against ``json.JSONDecodeError``.  If the Sentry API returns a
2xx status with a non-JSON body (maintenance page, gateway HTML, truncated
response), a bare ``json.JSONDecodeError`` propagates instead of a clear
warning log.

These tests FAIL (RED) against the current code because the unguarded
``resp.json()`` raises ``json.JSONDecodeError`` instead of returning a
graceful fallback (empty list / None) with a descriptive log message.
"""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from config import Credentials
from sentry_loop import SentryLoop
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


def _make_loop(tmp_path):
    config = ConfigFactory.create(repo_root=tmp_path)
    object.__setattr__(config, "sentry_org", "test-org")
    object.__setattr__(config, "sentry_project_filter", "")
    prs = MagicMock()
    deps = _make_deps()
    creds = Credentials(sentry_auth_token="sntryu_test")
    return SentryLoop(config=config, prs=prs, deps=deps, credentials=creds)


def _html_response(url: str = "https://sentry.io/api/0/test") -> httpx.Response:
    """Build a 200 OK response with HTML body (simulating a maintenance page)."""
    return httpx.Response(
        status_code=200,
        request=httpx.Request("GET", url),
        content=b"<html><body>Sentry is undergoing maintenance</body></html>",
        headers={"content-type": "text/html"},
    )


class TestIssue6656ListProjectsJsonDecodeError:
    """_list_projects raises json.JSONDecodeError on non-JSON 200 response
    instead of returning an empty list with a descriptive warning."""

    @pytest.mark.asyncio
    async def test_list_projects_non_json_response_raises_json_decode_error(
        self,
        tmp_path,
    ) -> None:
        """Demonstrates the bug: a 200 response with HTML body causes an
        unguarded json.JSONDecodeError to propagate from _list_projects.

        Once fixed, this method should return an empty list and log a warning
        instead of raising.
        """
        loop = _make_loop(tmp_path)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_html_response())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sentry_loop.httpx.AsyncClient", return_value=mock_client):
            # BUG: this raises json.JSONDecodeError instead of returning []
            with pytest.raises(json.JSONDecodeError):
                await loop._list_projects()


class TestIssue6656FetchUnresolvedJsonDecodeError:
    """_fetch_unresolved raises json.JSONDecodeError on non-JSON 200 response
    instead of returning an empty list with a descriptive warning."""

    @pytest.mark.asyncio
    async def test_fetch_unresolved_non_json_response_raises_json_decode_error(
        self,
        tmp_path,
    ) -> None:
        """Demonstrates the bug: a 200 response with HTML body causes an
        unguarded json.JSONDecodeError to propagate from _fetch_unresolved.

        Once fixed, this method should return an empty list and log a warning
        instead of raising.
        """
        loop = _make_loop(tmp_path)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_html_response())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sentry_loop.httpx.AsyncClient", return_value=mock_client):
            # BUG: this raises json.JSONDecodeError instead of returning []
            with pytest.raises(json.JSONDecodeError):
                await loop._fetch_unresolved("test-project")


class TestIssue6656FetchLatestEventJsonDecodeError:
    """_fetch_latest_event raises json.JSONDecodeError on non-JSON 200 response
    instead of returning None with a descriptive warning."""

    @pytest.mark.asyncio
    async def test_fetch_latest_event_non_json_response_raises_json_decode_error(
        self,
        tmp_path,
    ) -> None:
        """Demonstrates the bug: a 200 response with HTML body causes an
        unguarded json.JSONDecodeError to propagate from _fetch_latest_event.

        Although _fetch_latest_event has a broad ``except Exception`` handler,
        ``reraise_on_credit_or_bug()`` re-raises JSONDecodeError because it is
        not classified as a credit or known-bug exception.  The result is that
        the JSONDecodeError propagates up with no descriptive context about the
        malformed Sentry response.

        Once fixed, this method should return None and log a clear warning
        about non-JSON response instead of raising.
        """
        loop = _make_loop(tmp_path)

        mock_client = AsyncMock()
        mock_client.get = AsyncMock(return_value=_html_response())
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)

        with patch("sentry_loop.httpx.AsyncClient", return_value=mock_client):
            # BUG: reraise_on_credit_or_bug re-raises JSONDecodeError
            with pytest.raises(json.JSONDecodeError):
                await loop._fetch_latest_event("12345")
