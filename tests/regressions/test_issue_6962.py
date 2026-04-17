"""Regression test for issue #6962.

Bug: ``HindsightClient`` wraps ``httpx.AsyncClient`` but does not implement
the async context manager protocol (``__aenter__`` / ``__aexit__``).  Callers
in ``server.py`` and ``service_registry.py`` construct instances without any
guarantee that ``close()`` is called on the happy path.  Over long-running
server processes, this leaks HTTP connections.

Issue #6484 covers the error-path leak; this issue covers the **normal
teardown path** — specifically that callers cannot use ``async with`` because
the protocol is missing.

Expected behaviour after fix:
  - ``HindsightClient`` supports ``async with`` via ``__aenter__``/``__aexit__``.
  - ``__aexit__`` closes the underlying ``httpx.AsyncClient``.
  - All construction sites use the context manager or call ``close()`` in a
    ``finally`` block.

These tests assert the CORRECT (post-fix) behaviour and are therefore
RED against the current buggy code.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))


class TestHindsightClientHappyPathCleanup:
    """HindsightClient must support async context manager for happy-path cleanup."""

    def test_implements_aenter(self) -> None:
        """HindsightClient must define __aenter__ so callers can write 'async with'."""
        from hindsight import HindsightClient

        assert hasattr(HindsightClient, "__aenter__"), (
            "HindsightClient missing __aenter__ — callers cannot use "
            "'async with HindsightClient(...) as client:' for guaranteed cleanup"
        )

    def test_implements_aexit(self) -> None:
        """HindsightClient must define __aexit__ so 'async with' cleans up."""
        from hindsight import HindsightClient

        assert hasattr(HindsightClient, "__aexit__"), (
            "HindsightClient missing __aexit__ — 'async with' cannot guarantee "
            "close() is called, leading to connection leaks on normal teardown"
        )

    @pytest.mark.asyncio
    async def test_context_manager_closes_client_on_normal_exit(self) -> None:
        """The happy path: 'async with' must close the httpx client when the
        block completes normally (no exception).

        This is the core of #6962 — without the context manager protocol,
        the only way to close is an explicit ``await client.close()`` call
        that callers in server.py and service_registry.py currently omit.
        """
        from hindsight import HindsightClient

        async with HindsightClient("http://localhost:9999") as client:
            # Inside the block the connection should be open
            assert not client._client.is_closed, (
                "httpx.AsyncClient should be open inside 'async with' block"
            )

        # After exiting the block the connection must be closed
        assert client._client.is_closed, (
            "httpx.AsyncClient not closed after 'async with' block exited normally — "
            "this is the happy-path connection leak described in #6962"
        )

    @pytest.mark.asyncio
    async def test_context_manager_closes_client_on_exception(self) -> None:
        """Even when an exception occurs inside the block, __aexit__ must
        still close the underlying client to prevent leaks."""
        from hindsight import HindsightClient

        with pytest.raises(ValueError, match="simulated"):
            async with HindsightClient("http://localhost:9999") as client:
                inner_client = client._client
                raise ValueError("simulated error inside context manager")

        assert inner_client.is_closed, (
            "httpx.AsyncClient not closed after exception inside 'async with' — "
            "connection leaked on error path"
        )

    @pytest.mark.asyncio
    async def test_bare_construction_leaks_without_explicit_close(self) -> None:
        """Demonstrate the current leak: constructing HindsightClient without
        calling close() leaves the httpx.AsyncClient open.

        This test documents the problem — it should PASS on current code
        (proving the leak exists) and continue to pass after the fix (the
        fix doesn't change bare construction behaviour, just adds the
        context manager alternative).
        """
        from hindsight import HindsightClient

        client = HindsightClient("http://localhost:9999")
        try:
            # Without close(), the connection remains open — this is the leak
            assert not client._client.is_closed, (
                "Expected httpx.AsyncClient to be open (leaked) when close() "
                "is never called — this documents the #6962 bug"
            )
        finally:
            # Clean up so the test itself doesn't leak
            await client.close()
