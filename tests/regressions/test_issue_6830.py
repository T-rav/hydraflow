"""Regression test for issue #6830.

``CodeGroomingLoop._do_work`` wraps ``_run_audit()`` in a bare
``except Exception`` that logs and returns ``{"filed": 0, "error": True}``.
Because ``_run_audit`` calls ``stream_claude_process``, which can raise
``AuthenticationError`` or ``CreditExhaustedError``, those fatal signals
are silently absorbed before they reach ``BaseBackgroundLoop._execute_cycle``
(which would re-raise them to halt the loop).

These tests assert that ``AuthenticationError`` and ``CreditExhaustedError``
propagate out of ``_do_work`` — they will FAIL (RED) until the handler is
fixed to re-raise those exceptions before the generic catch-all.
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, patch

import pytest

from code_grooming_loop import CodeGroomingLoop
from subprocess_util import AuthenticationError, CreditExhaustedError
from tests.helpers import make_bg_loop_deps

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_loop(
    tmp_path: Path,
) -> tuple[CodeGroomingLoop, AsyncMock, asyncio.Event]:
    """Build a CodeGroomingLoop with test-friendly defaults."""
    deps = make_bg_loop_deps(
        tmp_path,
        code_grooming_interval=86400,
        code_grooming_enabled=True,
    )
    pr_manager = AsyncMock()
    pr_manager.create_issue = AsyncMock(return_value=42)
    loop = CodeGroomingLoop(
        config=deps.config,
        pr_manager=pr_manager,
        deps=deps.loop_deps,
    )
    return loop, pr_manager, deps.stop_event


# ===========================================================================
# Tests — fatal errors must propagate out of _do_work
# ===========================================================================


class TestDoWorkPropagatesFatalErrors:
    """AuthenticationError and CreditExhaustedError must NOT be swallowed.

    ``BaseBackgroundLoop._execute_cycle`` re-raises these so the loop halts.
    If ``_do_work`` catches them first, operators never see the outage.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Regression for issue #6830 — fix not yet landed", strict=False
    )
    async def test_authentication_error_propagates(self, tmp_path: Path) -> None:
        """_do_work must let AuthenticationError escape.

        Currently FAILS because ``except Exception`` on line 103 catches it
        and returns ``{"filed": 0, "error": True}`` instead.
        """
        loop, _pm, _stop = _make_loop(tmp_path)

        with (
            patch.object(
                loop,
                "_run_audit",
                new_callable=AsyncMock,
                side_effect=AuthenticationError("bad token"),
            ),
            pytest.raises(AuthenticationError),
        ):
            await loop._do_work()

    @pytest.mark.asyncio
    @pytest.mark.xfail(
        reason="Regression for issue #6830 — fix not yet landed", strict=False
    )
    async def test_credit_exhausted_error_propagates(self, tmp_path: Path) -> None:
        """_do_work must let CreditExhaustedError escape.

        Currently FAILS because ``except Exception`` on line 103 catches it
        and returns ``{"filed": 0, "error": True}`` instead.
        """
        loop, _pm, _stop = _make_loop(tmp_path)

        with (
            patch.object(
                loop,
                "_run_audit",
                new_callable=AsyncMock,
                side_effect=CreditExhaustedError("credits gone"),
            ),
            pytest.raises(CreditExhaustedError),
        ):
            await loop._do_work()


class TestDoWorkStillCatchesGenericErrors:
    """Generic RuntimeError must still be caught gracefully (no regression)."""

    @pytest.mark.asyncio
    async def test_runtime_error_returns_error_dict(self, tmp_path: Path) -> None:
        """A plain RuntimeError should be caught and return the error dict."""
        loop, _pm, _stop = _make_loop(tmp_path)

        with patch.object(
            loop,
            "_run_audit",
            new_callable=AsyncMock,
            side_effect=RuntimeError("something broke"),
        ):
            result = await loop._do_work()

        assert result is not None
        assert result["filed"] == 0
        assert result["error"] is True
