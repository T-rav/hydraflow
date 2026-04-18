"""Regression test for issue #6777.

Bug: ``HindsightClient.health_check()`` catches only ``httpx.HTTPError``,
but its contract is to return ``False`` for *any* connection failure.
Several exception types can escape the narrow handler:

- ``httpx.StreamError`` and subclasses (``StreamClosed``, ``ResponseNotRead``,
  etc.) are ``RuntimeError`` subclasses, **not** ``httpx.HTTPError`` subclasses.
- Non-httpx exceptions (``OSError``, ``ssl.SSLError``) that might escape
  httpx's internal wrapping layer in edge cases.

A health-check function must never crash — it should return ``False`` for
*any* failure.  The current code's ``except httpx.HTTPError`` is narrower
than the function's intent and the acceptance criteria:
    "health_check() returns False for all connection-level failures,
     not just HTTP errors"

These tests assert the **correct** behaviour and are expected to be RED
against the current (buggy) code.
"""

from __future__ import annotations

from unittest.mock import AsyncMock, patch

import pytest

# ---------------------------------------------------------------------------
# health_check — narrow exception handler
# ---------------------------------------------------------------------------


class TestHealthCheckExceptionHandling:
    """health_check() must return False for ALL failures, not just httpx.HTTPError."""

    @pytest.mark.asyncio()
    @pytest.mark.xfail(reason="Regression for issue #6777 — fix not yet landed", strict=False)
    async def test_health_check_returns_false_on_stream_error(self) -> None:
        """httpx.StreamError is NOT a subclass of httpx.HTTPError — it inherits
        from RuntimeError.  health_check() should catch it and return False,
        but the current ``except httpx.HTTPError`` lets it crash through.
        """
        import httpx

        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        try:
            with patch.object(
                client._client,
                "get",
                new_callable=AsyncMock,
                side_effect=httpx.StreamError("response stream broken"),
            ):
                result = await client.health_check()
            assert result is False, (
                "health_check() should return False when httpx.StreamError is raised, "
                "but it propagated the exception instead"
            )
        finally:
            await client.close()

    @pytest.mark.asyncio()
    @pytest.mark.xfail(reason="Regression for issue #6777 — fix not yet landed", strict=False)
    async def test_health_check_returns_false_on_os_error(self) -> None:
        """An OSError from a low-level socket failure is not an httpx.HTTPError.
        health_check() should catch it and return False.
        """
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        try:
            with patch.object(
                client._client,
                "get",
                new_callable=AsyncMock,
                side_effect=OSError("Network is unreachable"),
            ):
                result = await client.health_check()
            assert result is False, (
                "health_check() should return False when OSError is raised, "
                "but it propagated the exception instead"
            )
        finally:
            await client.close()

    @pytest.mark.asyncio()
    @pytest.mark.xfail(reason="Regression for issue #6777 — fix not yet landed", strict=False)
    async def test_health_check_returns_false_on_runtime_error(self) -> None:
        """Any unexpected RuntimeError should not crash a health check."""
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        try:
            with patch.object(
                client._client,
                "get",
                new_callable=AsyncMock,
                side_effect=RuntimeError("unexpected transport state"),
            ):
                result = await client.health_check()
            assert result is False, (
                "health_check() should return False when RuntimeError is raised, "
                "but it propagated the exception instead"
            )
        finally:
            await client.close()


# ---------------------------------------------------------------------------
# health_check — confirm httpx.HTTPError IS caught (baseline sanity check)
# ---------------------------------------------------------------------------


class TestHealthCheckBaselineSanity:
    """Verify httpx.HTTPError and its subclasses are handled (expected GREEN)."""

    @pytest.mark.asyncio()
    async def test_health_check_returns_false_on_connect_timeout(self) -> None:
        """ConnectTimeout IS a subclass of HTTPError in httpx 0.28 — this
        should pass (GREEN) to document that the issue's specific claim about
        ConnectTimeout is incorrect for the installed httpx version.
        """
        import httpx

        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        try:
            with patch.object(
                client._client,
                "get",
                new_callable=AsyncMock,
                side_effect=httpx.ConnectTimeout(
                    "timed out",
                    request=httpx.Request("GET", "http://localhost:9999/health"),
                ),
            ):
                result = await client.health_check()
            assert result is False
        finally:
            await client.close()
