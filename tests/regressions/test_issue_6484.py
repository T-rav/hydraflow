"""Regression test for issue #6484.

Bug: ``HindsightClient`` wraps ``httpx.AsyncClient`` but:

1. Does not implement the async context manager protocol (``__aenter__`` /
   ``__aexit__``).  Callers cannot use ``async with`` and must remember to
   call ``close()`` explicitly — which ``service_registry.build_services``
   does not do.  On orchestrator shutdown the connection pool is never
   drained, producing ``ResourceWarning`` and leaking HTTP connections.

2. ``health_check()`` only catches ``httpx.HTTPError``.  Any non-httpx
   exception (``RuntimeError``, ``OSError``, ``anyio`` errors during pool
   shutdown) propagates through the "never-raise" contract, crashing the
   caller's health-polling loop.

Expected behaviour after fix:
  - ``HindsightClient`` supports ``async with`` (closes the underlying
    ``httpx.AsyncClient`` in ``__aexit__``).
  - ``health_check()`` catches ``Exception`` (or at minimum a broader set
    than ``httpx.HTTPError``) and returns ``False``.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from hindsight import HindsightClient

# ---------------------------------------------------------------------------
# 1. Async context manager support
# ---------------------------------------------------------------------------


class TestAsyncContextManagerProtocol:
    """HindsightClient must be an async context manager to prevent leaks."""

    def test_has_aenter(self) -> None:
        """HindsightClient must implement __aenter__ for 'async with'."""
        assert hasattr(HindsightClient, "__aenter__"), (
            "HindsightClient missing __aenter__ — cannot use 'async with', "
            "leading to connection pool leaks when callers forget close()"
        )

    def test_has_aexit(self) -> None:
        """HindsightClient must implement __aexit__ for 'async with'."""
        assert hasattr(HindsightClient, "__aexit__"), (
            "HindsightClient missing __aexit__ — cannot use 'async with', "
            "leading to connection pool leaks when callers forget close()"
        )

    @pytest.mark.asyncio
    async def test_async_with_closes_underlying_client(self) -> None:
        """'async with HindsightClient(...)' must close the httpx client on exit."""
        async with HindsightClient("http://localhost:9999") as client:
            assert not client._client.is_closed
        assert client._client.is_closed


# ---------------------------------------------------------------------------
# 2. health_check exception handling
# ---------------------------------------------------------------------------


class TestHealthCheckNeverRaiseContract:
    """health_check() must return False on ALL errors, not just httpx.HTTPError."""

    @pytest.mark.asyncio
    async def test_returns_false_on_runtime_error(self) -> None:
        """RuntimeError from transport layer must be caught, not propagated.

        This can happen when the event loop is closing or the connection
        pool is in a degraded state.

        BUG (current): only ``httpx.HTTPError`` is caught, so RuntimeError
        propagates and crashes the health-polling loop.
        """
        client = HindsightClient("http://localhost:9999")
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            side_effect=RuntimeError("Event loop is closed"),
        )
        try:
            result = await client.health_check()
            assert result is False
        finally:
            await client.close()

    @pytest.mark.asyncio
    async def test_returns_false_on_os_error(self) -> None:
        """OSError from socket layer must be caught, not propagated.

        BUG (current): only ``httpx.HTTPError`` is caught, so OSError
        propagates.
        """
        client = HindsightClient("http://localhost:9999")
        client._client = AsyncMock()
        client._client.get = AsyncMock(
            side_effect=OSError("Connection refused"),
        )
        try:
            result = await client.health_check()
            assert result is False
        finally:
            await client.close()
