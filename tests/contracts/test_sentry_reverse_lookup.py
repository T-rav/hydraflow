"""Sentry reverse-lookup contract test (spec §3.2). httpx-mock-driven."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import httpx
import pytest

from sentry.reverse_lookup import query_sentry_by_title


def _make_mock_response(status_code: int = 200, payload: object = None) -> MagicMock:
    resp = MagicMock(spec=httpx.Response)
    resp.status_code = status_code
    if status_code >= 400:
        resp.raise_for_status.side_effect = httpx.HTTPStatusError(
            f"HTTP {status_code}",
            request=MagicMock(),
            response=resp,
        )
    else:
        resp.raise_for_status.return_value = None
        resp.json.return_value = payload or []
    return resp


@pytest.mark.asyncio
async def test_parses_sentry_issues_response() -> None:
    """Cassette: realistic Sentry issues-search payload → parsed events."""
    mock_resp = _make_mock_response(
        200,
        [
            {
                "id": "1234567",
                "title": "ConnectionError: timeout",
                "level": "error",
                "lastSeen": "2026-04-25T12:00:00Z",
                "permalink": "https://sentry.io/organizations/myorg/issues/1234567/",
                "count": 42,
                "userCount": 7,
                "metadata": {"value": "Connection to db.local timed out after 30s"},
                "culprit": "ingest.fetcher",
            },
        ],
    )

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    out = await query_sentry_by_title(
        "ConnectionError: timeout",
        auth_token="tok",
        org="myorg",
        client=mock_client,
    )
    assert len(out) == 1
    e = out[0]
    assert e.sentry_id == "1234567"
    assert e.event_count == 42
    assert e.user_count == 7
    assert e.message == "Connection to db.local timed out after 30s"


@pytest.mark.asyncio
async def test_returns_empty_on_http_error() -> None:
    mock_resp = _make_mock_response(500)

    mock_client = AsyncMock(spec=httpx.AsyncClient)
    mock_client.get = AsyncMock(return_value=mock_resp)
    mock_client.aclose = AsyncMock()

    out = await query_sentry_by_title(
        "anything", auth_token="tok", org="myorg", client=mock_client
    )
    assert out == []


@pytest.mark.asyncio
async def test_returns_empty_when_no_creds() -> None:
    out = await query_sentry_by_title("x", auth_token="", org="myorg")
    assert out == []
