"""Regression test for issue #6362.

Bug: HindsightClient creates an httpx.AsyncClient at construction time but
does not implement the async context manager protocol (__aenter__/__aexit__)
and service_registry.py never registers close() in a shutdown hook.  This
means the underlying connection pool is never flushed on shutdown, producing
ResourceWarning and leaking file descriptors.

These tests assert the *correct* behaviour, so they are RED against the
current (buggy) code.
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

import pytest

# Ensure src/ is importable
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from hindsight import HindsightClient  # noqa: E402


class TestHindsightClientContextManager:
    """HindsightClient should support the async context manager protocol."""

    def test_has_aenter(self) -> None:
        """HindsightClient must define __aenter__ for use as 'async with'."""
        assert hasattr(HindsightClient, "__aenter__"), (
            "HindsightClient does not implement __aenter__ — "
            "cannot be used as an async context manager"
        )

    def test_has_aexit(self) -> None:
        """HindsightClient must define __aexit__ for use as 'async with'."""
        assert hasattr(HindsightClient, "__aexit__"), (
            "HindsightClient does not implement __aexit__ — "
            "cannot be used as an async context manager"
        )


class TestHindsightClientResourceWarning:
    """Dropping a HindsightClient without close() must not leak resources."""

    @pytest.mark.asyncio
    async def test_no_resource_warning_on_gc(self) -> None:
        """Creating and discarding a HindsightClient without close() must
        not emit ResourceWarning about unclosed connections.

        This test is RED while the bug exists: the client's internal
        httpx.AsyncClient holds open connections that Python's GC will
        warn about when they are collected without being closed.
        """
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter("always")

            client = HindsightClient("http://localhost:9999", timeout=1)
            # Drop reference without calling close() — simulates shutdown
            # without cleanup, which is the bug.
            del client

            # Force collection so the ResourceWarning surfaces now.
            import gc

            gc.collect()

            resource_warnings = [
                w for w in caught if issubclass(w.category, ResourceWarning)
            ]
            # The bug is that ResourceWarning IS emitted here.  After the
            # fix (context manager or shutdown hook), no warning should appear.
            assert not resource_warnings, (
                f"ResourceWarning emitted for unclosed HindsightClient: "
                f"{[str(w.message) for w in resource_warnings]}"
            )
