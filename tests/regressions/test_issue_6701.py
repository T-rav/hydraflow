"""Regression test for issue #6701.

``HindsightClient.retain``, ``recall``, and ``reflect`` call ``resp.json()``
without catching ``json.JSONDecodeError``.  If the Hindsight server returns
a 200 with a malformed or truncated JSON body (possible during restart,
memory pressure, or partial network failure), the raw ``JSONDecodeError``
propagates up to callers that use the client directly (e.g. ``memory_audit.py``,
``hindsight_wal.py``) rather than through the safe wrappers.

These tests simulate a 200 response with a malformed body and assert that
the methods handle the decode error gracefully — either by returning a
sensible default or raising a descriptive ``RuntimeError``.

All three tests will FAIL (RED) until the methods guard ``resp.json()``.
"""

from __future__ import annotations

import httpx
import pytest

from hindsight import HindsightClient
from hindsight_types import Bank

# ---------------------------------------------------------------------------
# Helpers — mock transport returning 200 with malformed JSON
# ---------------------------------------------------------------------------

MALFORMED_BODY = b"<html>Service Unavailable</html>"


def _malformed_transport(request: httpx.Request) -> httpx.Response:
    """Return a 200 OK with a non-JSON body for every request."""
    return httpx.Response(
        status_code=200,
        content=MALFORMED_BODY,
        headers={"Content-Type": "application/json"},
    )


@pytest.fixture()
def client() -> HindsightClient:
    """Build a HindsightClient backed by a transport that returns bad JSON."""
    c = HindsightClient("http://localhost:9999")
    # Replace the internal httpx.AsyncClient with one using our mock transport
    c._client = httpx.AsyncClient(
        base_url="http://localhost:9999",
        transport=httpx.MockTransport(_malformed_transport),
    )
    return c


# ---------------------------------------------------------------------------
# Test 1 — retain must not raise JSONDecodeError on malformed response
# ---------------------------------------------------------------------------


class TestRetainMalformedResponse:
    """retain() should handle a malformed 200 response without raising
    a raw JSONDecodeError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6701 — fix not yet landed", strict=False)
    async def test_retain_malformed_json_does_not_raise_json_error(
        self, client: HindsightClient
    ) -> None:
        """When the Hindsight server returns 200 with a non-JSON body,
        retain() should either return a sensible value or raise a
        descriptive RuntimeError — NOT a raw JSONDecodeError.

        Fails until retain() guards resp.json() with a try/except.
        """
        with pytest.raises(RuntimeError):
            await client.retain(Bank.TRIBAL, "test content")


# ---------------------------------------------------------------------------
# Test 2 — recall must not raise JSONDecodeError on malformed response
# ---------------------------------------------------------------------------


class TestRecallMalformedResponse:
    """recall() should handle a malformed 200 response without raising
    a raw JSONDecodeError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6701 — fix not yet landed", strict=False)
    async def test_recall_malformed_json_returns_empty_list(
        self, client: HindsightClient
    ) -> None:
        """When the Hindsight server returns 200 with a non-JSON body,
        recall() should return an empty list — NOT raise JSONDecodeError.

        Fails until recall() guards resp.json() with a try/except.
        """
        result = await client.recall(Bank.TRIBAL, "test query")
        assert result == [], (
            "recall() should return [] on malformed JSON, "
            "but raised an exception instead"
        )


# ---------------------------------------------------------------------------
# Test 3 — reflect must not raise JSONDecodeError on malformed response
# ---------------------------------------------------------------------------


class TestReflectMalformedResponse:
    """reflect() should handle a malformed 200 response without raising
    a raw JSONDecodeError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6701 — fix not yet landed", strict=False)
    async def test_reflect_malformed_json_returns_empty_string(
        self, client: HindsightClient
    ) -> None:
        """When the Hindsight server returns 200 with a non-JSON body,
        reflect() should return an empty string — NOT raise JSONDecodeError.

        Fails until reflect() guards resp.json() with a try/except.
        """
        result = await client.reflect(Bank.TRIBAL, "test query")
        assert result == "", (
            "reflect() should return '' on malformed JSON, "
            "but raised an exception instead"
        )
