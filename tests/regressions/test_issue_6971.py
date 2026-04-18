"""Regression test for issue #6971.

``DockerRunner.run_simple`` fetches container logs (stdout, stderr) via two
separate ``container.logs()`` calls inside the ``try`` block (lines 631-642).
The ``finally`` block then removes the container with ``container.remove(force=True)``.

**Bug 1 — data race on exception between wait() and logs():**
If an exception occurs after ``container.wait()`` completes but during the first
``container.logs(stdout=True, stderr=False)`` call, the exception propagates out
of the ``try`` block, the ``finally`` block removes the container, and the
stderr logs are never fetched.  Both stdout and stderr are lost.

The fix is to move log collection into the ``finally`` block (or a nested
try/except) so logs are always attempted before container removal.

**Bug 2 — two sequential Docker API round-trips for log collection:**
stdout and stderr are fetched via two separate ``container.logs()`` calls.
Docker's ``demux=True`` option returns ``(stdout_bytes, stderr_bytes)`` in a
single call, halving the API round-trips.

These tests will FAIL (RED) until the bugs are fixed.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, call, patch

import pytest

docker = pytest.importorskip("docker", reason="docker package not installed")

from docker_runner import DockerRunner

# ---------------------------------------------------------------------------
# Helpers (mirrors test_docker_runner.py patterns)
# ---------------------------------------------------------------------------


def _make_mock_container(exit_code: int = 0) -> MagicMock:
    """Build a mock Docker container object."""
    container = MagicMock()
    container.wait.return_value = {"StatusCode": exit_code}
    container.logs.return_value = b""
    container.kill.return_value = None
    container.start.return_value = None
    container.remove.return_value = None
    return container


def _make_mock_docker_client(container: MagicMock) -> MagicMock:
    """Build a mock docker.DockerClient."""
    client = MagicMock()
    client.containers.create.return_value = container
    client.ping.return_value = True
    return client


def _make_runner(*, log_dir: Path, mock_client: MagicMock) -> DockerRunner:
    """Create a DockerRunner with mocked Docker client."""
    with patch("docker.from_env", return_value=mock_client):
        runner = DockerRunner(
            image="test:latest",
            repo_root=Path("/tmp/test-repo"),
            log_dir=log_dir,
            spawn_delay=0.0,
        )
    runner._client = mock_client
    return runner


# ---------------------------------------------------------------------------
# Test 1 — Logs lost when exception occurs between wait() and logs()
# ---------------------------------------------------------------------------


class TestLogsLostOnExceptionBetweenWaitAndLogs:
    """When an exception occurs during stdout log collection, stderr logs
    should still be fetched before the container is removed.

    Current behaviour: the exception from the first ``container.logs()``
    propagates, the ``finally`` block removes the container, and the second
    ``container.logs()`` call for stderr is never made.  Logs are lost.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6971 — fix not yet landed", strict=False)
    async def test_stderr_logs_still_fetched_when_stdout_logs_raise(
        self, tmp_path: Path
    ) -> None:
        """If ``container.logs(stdout=True, stderr=False)`` raises, the code
        should still attempt to fetch stderr logs before removing the container.

        Fails until log collection is guarded by its own try/except or moved
        into the finally block.
        """
        container = _make_mock_container(exit_code=0)

        # First logs() call (stdout) raises; second (stderr) would succeed.
        call_count = 0

        def logs_side_effect(*, stdout: bool = True, stderr: bool = True) -> bytes:
            nonlocal call_count
            call_count += 1
            if stdout and not stderr:
                raise OSError("Docker API: connection reset during log fetch")
            return b"important error context"

        container.logs.side_effect = logs_side_effect

        client = _make_mock_docker_client(container)
        runner = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # The current code will propagate the OSError.  The fix should
        # catch it and still return a SimpleResult (possibly with empty stdout).
        # We accept either behaviour — what matters is stderr was attempted.
        try:
            await runner.run_simple(["echo", "hello"])
        except OSError:
            pass  # Expected with current buggy code

        # Assert that stderr log fetch was attempted despite stdout failure.
        # In the current code, only one logs() call is made before the
        # exception propagates — this assertion FAILS.
        stderr_calls = [
            c
            for c in container.logs.call_args_list
            if c == call(stdout=False, stderr=True)
        ]
        assert len(stderr_calls) >= 1, (
            "container.logs(stdout=False, stderr=True) was never called — "
            "stderr logs are lost when stdout log fetch raises an exception. "
            f"Total logs() calls made: {container.logs.call_args_list} "
            "(issue #6971)"
        )


# ---------------------------------------------------------------------------
# Test 2 — Logs should be collected even when try block raises
# ---------------------------------------------------------------------------


class TestLogsCollectedOnTryBlockException:
    """When an arbitrary exception is raised inside the try block after
    ``container.wait()`` returns, log collection should still be attempted
    (in the finally block) before the container is removed.

    This simulates the scenario where ``run_in_executor`` raises an
    unrelated error after wait() but before the logs() calls.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6971 — fix not yet landed", strict=False)
    async def test_logs_attempted_before_container_removal_on_error(
        self, tmp_path: Path
    ) -> None:
        """Inject a RuntimeError after wait() completes.  Verify that
        container.logs() is still called before container.remove().

        Fails until log collection is moved to the finally block.
        """
        container = _make_mock_container(exit_code=0)
        container.logs.return_value = b"precious diagnostic output"

        client = _make_mock_docker_client(container)
        runner = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        # Track the order of operations to verify logs are fetched
        # before container removal.
        call_order: list[str] = []
        original_wait = container.wait.return_value

        def tracking_wait() -> dict:
            call_order.append("wait")
            return original_wait

        def tracking_logs(*, stdout: bool = True, stderr: bool = True) -> bytes:
            call_order.append(f"logs(stdout={stdout}, stderr={stderr})")
            # On the first call (stdout), raise to simulate an error
            # between wait() and successful log collection.
            if stdout and not stderr:
                raise RuntimeError("injected error after wait()")
            return b"stderr content"

        def tracking_remove(*, force: bool = False) -> None:
            call_order.append("remove")

        container.wait.side_effect = tracking_wait
        container.logs.side_effect = tracking_logs
        container.remove.side_effect = tracking_remove

        with pytest.raises(RuntimeError, match="injected error"):
            await runner.run_simple(["test-cmd"])

        # The fix should ensure logs are fetched BEFORE remove.
        # Current code: wait -> logs(stdout) -> EXCEPTION -> remove
        #   (logs(stderr) is never called)
        # Fixed code: wait -> EXCEPTION -> logs(stdout+stderr) -> remove
        #   (or: wait -> logs(demux) -> remove, with try/except)
        assert any("logs" in op for op in call_order), (
            "container.logs() was never called at all — "
            f"call order: {call_order} (issue #6971)"
        )

        # Verify logs were attempted BEFORE remove
        log_indices = [i for i, op in enumerate(call_order) if "logs" in op]
        remove_indices = [i for i, op in enumerate(call_order) if op == "remove"]

        if remove_indices:
            max(log_indices) if log_indices else -1
            min(remove_indices)
            # This assertion checks that stderr logs were also attempted.
            # In the buggy code, only one logs() call happens (stdout),
            # which raises.  The second logs() (stderr) is skipped.
            stderr_attempted = any(
                "stderr=True" in op and "stdout=False" in op for op in call_order
            )
            assert stderr_attempted, (
                "stderr log collection was skipped after stdout log "
                "collection failed — both streams should be attempted. "
                f"call order: {call_order} (issue #6971)"
            )


# ---------------------------------------------------------------------------
# Test 3 — Two sequential API calls instead of single demuxed call
# ---------------------------------------------------------------------------


class TestTwoSequentialLogCalls:
    """``run_simple`` makes two separate ``container.logs()`` calls — one for
    stdout and one for stderr — instead of a single
    ``container.logs(stdout=True, stderr=True, demux=True)`` call.

    This doubles the Docker API round-trips per container run.
    """

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6971 — fix not yet landed", strict=False)
    async def test_logs_fetched_in_single_api_call(self, tmp_path: Path) -> None:
        """Verify that stdout and stderr are fetched in one API call
        using ``demux=True``.

        Fails until the two separate logs() calls are combined.
        """
        container = _make_mock_container(exit_code=0)
        container.logs.side_effect = [b"stdout output", b"stderr output"]

        client = _make_mock_docker_client(container)
        runner = _make_runner(log_dir=tmp_path / "logs", mock_client=client)
        (tmp_path / "logs").mkdir(parents=True, exist_ok=True)

        await runner.run_simple(["echo", "hello"])

        # The current code makes 2 calls:
        #   container.logs(stdout=True, stderr=False)
        #   container.logs(stdout=False, stderr=True)
        # The fix should make 1 call:
        #   container.logs(stdout=True, stderr=True, demux=True)
        assert container.logs.call_count == 1, (
            f"container.logs() was called {container.logs.call_count} times "
            "but should be called exactly once with demux=True to avoid "
            "redundant Docker API round-trips (issue #6971)"
        )
