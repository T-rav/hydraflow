"""Regression test for issue #6578.

``DockerRunner._ensure_client`` uses ``time.sleep(delay)`` in its retry loop.
Since it is called from async contexts via ``run_in_executor``, each retrying
call blocks a thread-pool worker for up to ``max_retries * delay`` seconds.
Under concurrent container spawning with Docker unavailable, this exhausts the
default executor thread pool, starving all other ``run_in_executor`` work
(git ops, disk I/O, memory sync).

These tests will fail (RED) until ``_ensure_client``'s retry wait is made
non-blocking (e.g. ``asyncio.sleep``) or concurrent retries are gated by a
lock so only one thread sleeps while others fast-fail.
"""

from __future__ import annotations

import asyncio
import time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from docker_runner import DockerRunner


def _make_failing_runner() -> DockerRunner:
    """Create a DockerRunner whose Docker client always fails ping."""
    failing_client = MagicMock()
    failing_client.ping.side_effect = ConnectionError("Docker daemon not running")

    mock_docker_mod = MagicMock()
    mock_docker_mod.from_env.return_value = failing_client

    with patch.dict("sys.modules", {"docker": mock_docker_mod}):
        runner = DockerRunner(
            image="test:latest",
            repo_root=Path("/tmp/test-repo"),
            log_dir=Path("/tmp/test-logs"),
            spawn_delay=0.0,
        )
    runner._client = failing_client
    return runner


# ---------------------------------------------------------------------------
# Test 1 — Concurrent _ensure_client calls exhaust the thread pool
# ---------------------------------------------------------------------------


class TestEnsureClientExhaustsThreadPool:
    """_ensure_client's blocking time.sleep starves thread pool under load."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6578 — fix not yet landed", strict=False)
    async def test_thread_pool_starved_by_concurrent_retries(self) -> None:
        """When Docker is unavailable, concurrent _ensure_client calls via
        run_in_executor each block a thread with time.sleep.  A small pool
        becomes fully saturated, preventing any other work from executing.

        This test uses a 4-thread pool, submits 4 _ensure_client calls (each
        retrying with 1s delay × 3 retries = 3s blocking), then submits a
        trivial canary task.  The canary should complete immediately if the
        retry waits are non-blocking, but will be starved until at least one
        retry sequence finishes when time.sleep is used.

        Fails until _ensure_client stops blocking threads during retry waits.
        """
        runner = _make_failing_runner()
        pool = ThreadPoolExecutor(max_workers=4)
        loop = asyncio.get_running_loop()

        failing_client = MagicMock()
        failing_client.ping.side_effect = ConnectionError("Docker daemon not running")
        mock_docker_mod = MagicMock()
        mock_docker_mod.from_env.return_value = failing_client

        with patch.dict("sys.modules", {"docker": mock_docker_mod}):
            # Submit 4 _ensure_client calls — each will block a thread for
            # ~3s (3 retries × 1s delay) with time.sleep.
            retry_futures = [
                loop.run_in_executor(
                    pool,
                    lambda: runner._ensure_client(max_retries=3, delay=1.0),
                )
                for _ in range(4)
            ]

            # Brief pause to let all 4 threads enter the sleep loop.
            await asyncio.sleep(0.3)

            # Submit a trivial canary task to the same pool.
            canary_future = loop.run_in_executor(pool, lambda: "canary_ok")

            # If _ensure_client used asyncio.sleep (non-blocking), threads
            # would not be consumed during the wait and the canary would
            # run immediately.  With time.sleep, all 4 threads are blocked
            # and the canary cannot start until one finishes (~1s minimum).
            try:
                result = await asyncio.wait_for(canary_future, timeout=0.5)
            except TimeoutError:
                # This is the bug: thread pool is exhausted.
                pytest.fail(
                    "Thread pool exhausted: canary task could not run because "
                    "all workers are blocked in time.sleep retry loops — "
                    "_ensure_client must use non-blocking waits (issue #6578)"
                )

            assert result == "canary_ok"

        # Cleanup: let the retry futures finish (they'll raise RuntimeError).
        for f in retry_futures:
            f.cancel()
        pool.shutdown(wait=False, cancel_futures=True)


# ---------------------------------------------------------------------------
# Test 2 — _ensure_client uses time.sleep (blocking) not asyncio.sleep
# ---------------------------------------------------------------------------


class TestEnsureClientUsesBlockingSleep:
    """_ensure_client must not call time.sleep — it blocks executor threads."""

    @pytest.mark.xfail(reason="Regression for issue #6578 — fix not yet landed", strict=False)
    def test_retry_loop_calls_blocking_time_sleep(self) -> None:
        """Verify that _ensure_client currently calls time.sleep during retries.

        This is the structural root cause of the thread-pool exhaustion.  The
        fix should replace time.sleep with a non-blocking alternative (e.g.
        asyncio.sleep in an async wrapper).

        Fails once time.sleep is removed from _ensure_client's retry path.
        """
        runner = _make_failing_runner()

        sleep_calls: list[float] = []
        original_sleep = time.sleep

        def tracking_sleep(seconds: float) -> None:
            sleep_calls.append(seconds)
            # Use a tiny real sleep so we don't actually block
            original_sleep(0.01)

        failing_client = MagicMock()
        failing_client.ping.side_effect = ConnectionError("Docker daemon not running")
        mock_docker_mod = MagicMock()
        mock_docker_mod.from_env.return_value = failing_client

        with (
            patch.dict("sys.modules", {"docker": mock_docker_mod}),
            patch("time.sleep", side_effect=tracking_sleep),
        ):
            with pytest.raises(RuntimeError, match="not available after"):
                runner._ensure_client(max_retries=2, delay=5.0)

        # BUG: _ensure_client calls time.sleep(5.0) on each retry.
        # After the fix, this assertion should fail because time.sleep
        # will no longer be called in the retry loop.
        assert len(sleep_calls) == 0, (
            f"_ensure_client called time.sleep {len(sleep_calls)} time(s) with "
            f"delays {sleep_calls} — blocking sleep in a run_in_executor "
            f"context starves the thread pool (issue #6578)"
        )
