"""Regression test for issue #9510.

``DockerRunner.run_simple`` wraps ``loop.run_in_executor(None, container.wait)``
in ``asyncio.wait_for``.  When the surrounding task is cancelled (e.g. by a loop
watchdog), the ``finally`` block force-removes the container — but, unlike the
``TimeoutError`` branch, the cancel path issues **no** explicit
``container.kill()``.  Without the kill, the executor thread parked inside the
synchronous ``container.wait()`` only unblocks once the removal propagates, so
under rapid watchdog cancellations blocked threads accumulate in the default
``ThreadPoolExecutor``.

Expected behaviour (per the issue): mirror the ``TimeoutError`` branch by
calling ``container.kill()`` on ``asyncio.CancelledError`` before the ``finally``
removes the container, releasing the wait thread promptly.

This test cancels ``run_simple`` while it is blocked in ``container.wait()`` and
asserts that ``container.kill()`` was invoked.  It is RED until the cancel path
kills the container.
"""

from __future__ import annotations

import asyncio
import threading
from pathlib import Path

import pytest

docker = pytest.importorskip("docker", reason="docker package not installed")

from unittest.mock import MagicMock, patch

from docker_runner import DockerRunner


def _make_mock_container_blocking_wait(
    wait_entered: threading.Event,
    release: threading.Event,
) -> MagicMock:
    """Build a mock container whose ``wait()`` blocks until *release* is set."""

    def blocking_wait() -> dict[str, int]:
        wait_entered.set()
        # Block the executor thread the way a real container.wait() would.
        # The 30s safety timeout guarantees the thread can never leak even if
        # the test fails before releasing it.
        release.wait(timeout=30)
        return {"StatusCode": 0}

    container = MagicMock()
    container.wait.side_effect = blocking_wait
    container.logs.return_value = b""
    container.kill.return_value = None
    container.start.return_value = None
    container.remove.return_value = None
    return container


def _make_runner_with_container(container: MagicMock, log_dir: Path) -> DockerRunner:
    """Construct a DockerRunner backed by *container* without touching real Docker."""
    client = MagicMock()
    client.containers.create.return_value = container
    client.ping.return_value = True

    with patch("docker.from_env", return_value=client):
        runner = DockerRunner(
            image="hydra-agent:latest",
            repo_root=Path("/tmp/test-repo"),  # noqa: S108
            log_dir=log_dir,
            spawn_delay=0.0,
        )
    runner._client = client
    return runner


@pytest.mark.asyncio
async def test_run_simple_kills_container_on_cancellation(tmp_path: Path) -> None:
    wait_entered = threading.Event()
    release = threading.Event()
    container = _make_mock_container_blocking_wait(wait_entered, release)

    log_dir = tmp_path / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    runner = _make_runner_with_container(container, log_dir)

    task = asyncio.create_task(runner.run_simple(["sleep", "999"], timeout=999))

    # Wait until the executor thread is parked inside container.wait(), which
    # means run_simple is now suspended in `asyncio.wait_for(... container.wait)`.
    for _ in range(500):
        if wait_entered.is_set():
            break
        await asyncio.sleep(0.01)
    assert wait_entered.is_set(), "container.wait() never started blocking"

    try:
        task.cancel()
        with pytest.raises(asyncio.CancelledError):
            await task
    finally:
        # Release the parked wait thread so it cannot outlive the test.
        release.set()

    # The TimeoutError branch kills the container to release the wait thread.
    # The cancel path must do the same; today it only removes (via finally),
    # leaving the wait thread blocked until removal propagates.
    container.kill.assert_called_once()
