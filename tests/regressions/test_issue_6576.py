"""Regression test for issue #6576.

``_check_gh_auth`` spawns ``gh auth status`` as an async subprocess but calls
``await proc.wait()`` with no timeout.  If the ``gh`` CLI hangs (network
proxy issue, credential store deadlock), the preflight check never completes
and server startup is blocked forever.

By contrast, ``_check_docker()`` in the same file correctly uses
``subprocess.run(..., timeout=10)``.

These tests will fail (RED) until ``_check_gh_auth`` wraps its
``proc.wait()`` call in ``asyncio.wait_for`` with a bounded timeout.
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from preflight import CheckStatus, _check_gh_auth

# ---------------------------------------------------------------------------
# Test 1 — _check_gh_auth hangs indefinitely when proc.wait() never returns
# ---------------------------------------------------------------------------


class TestGhAuthTimeout:
    """_check_gh_auth must complete within a bounded time even when gh hangs."""

    @pytest.mark.asyncio
    async def test_check_gh_auth_completes_when_process_hangs(self) -> None:
        """If the gh subprocess hangs forever, _check_gh_auth should still
        return a FAIL result within a reasonable timeout (not block forever).

        This test simulates a hung process by making ``proc.wait()`` sleep
        indefinitely.  We wrap the call in a short external timeout — if
        ``_check_gh_auth`` has its own internal timeout, it will return a
        CheckResult before our outer timeout fires.  If it lacks an internal
        timeout, the outer timeout will fire, proving the bug.
        """

        async def hang_forever() -> int:
            """Simulate a process that never exits."""
            await asyncio.sleep(3600)
            return 0  # never reached

        mock_proc = MagicMock()
        mock_proc.wait = hang_forever
        mock_proc.kill = MagicMock()

        with (
            patch("preflight.shutil.which", return_value="/usr/bin/gh"),
            patch(
                "preflight.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
        ):
            # Give _check_gh_auth a generous 2s to respond on its own.
            # A correct implementation with a 10s timeout would need the mock
            # to respect cancellation, but since the function currently has
            # NO timeout at all, even 2s is enough to prove it hangs.
            try:
                result = await asyncio.wait_for(_check_gh_auth(), timeout=2.0)
            except TimeoutError:
                pytest.fail(
                    "_check_gh_auth blocked indefinitely when gh process hung — "
                    "proc.wait() has no timeout (issue #6576)"
                )

        # If we get here, the function returned before our outer timeout.
        # Verify it reported the hang as a failure.
        assert result.status == CheckStatus.FAIL, (
            "_check_gh_auth should return FAIL when the gh process hangs, "
            f"but returned {result.status.value}"
        )
        assert "timed out" in result.message.lower(), (
            "_check_gh_auth should mention timeout in its failure message, "
            f"but got: {result.message!r}"
        )


# ---------------------------------------------------------------------------
# Test 2 — _check_gh_auth must kill the hung subprocess before returning
# ---------------------------------------------------------------------------


class TestGhAuthKillsHungProcess:
    """When gh hangs and _check_gh_auth times out, it must kill the process."""

    @pytest.mark.asyncio
    async def test_hung_process_is_killed_on_timeout(self) -> None:
        """After timing out, the subprocess must be killed so it doesn't
        linger as an orphan.

        Fails until _check_gh_auth calls proc.kill() on timeout.
        """

        async def hang_forever() -> int:
            await asyncio.sleep(3600)
            return 0

        mock_proc = MagicMock()
        mock_proc.wait = hang_forever
        mock_proc.kill = MagicMock()

        with (
            patch("preflight.shutil.which", return_value="/usr/bin/gh"),
            patch(
                "preflight.asyncio.create_subprocess_exec",
                new_callable=AsyncMock,
                return_value=mock_proc,
            ),
        ):
            try:
                await asyncio.wait_for(_check_gh_auth(), timeout=2.0)
            except TimeoutError:
                pytest.fail(
                    "_check_gh_auth blocked indefinitely — cannot verify "
                    "kill() behavior because timeout is missing (issue #6576)"
                )

        mock_proc.kill.assert_called_once()
