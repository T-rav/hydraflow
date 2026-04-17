"""Regression test for issue #6959.

``DockerRunner.run_simple`` catches ``TimeoutError`` on container timeout and
re-raises it bare.  The ``SubprocessRunner`` protocol contract expects timeout
exceptions to be ``SubprocessTimeoutError`` so that callers can handle timeouts
uniformly regardless of the execution backend (host vs Docker).

The ``run_subprocess`` wrapper in ``subprocess_util`` does translate
``TimeoutError`` → ``SubprocessTimeoutError``, but any caller invoking
``run_simple`` directly (there are 15+ call sites) gets a raw ``TimeoutError``
from Docker mode, breaking ``except SubprocessTimeoutError`` guards.

These tests will fail (RED) until ``DockerRunner.run_simple`` translates
``TimeoutError`` to ``SubprocessTimeoutError`` on timeout.
"""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

docker = pytest.importorskip("docker", reason="docker package not installed")

from docker_runner import DockerRunner
from subprocess_util import SubprocessTimeoutError

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _make_mock_container() -> MagicMock:
    container = MagicMock()
    container.wait.return_value = {"StatusCode": 0}
    container.logs.return_value = b""
    container.kill.return_value = None
    container.start.return_value = None
    container.remove.return_value = None
    return container


def _make_mock_docker_client(container: MagicMock) -> MagicMock:
    client = MagicMock()
    client.containers.create.return_value = container
    client.ping.return_value = True
    return client


def _make_runner(*, mock_client: MagicMock, log_dir: Path) -> DockerRunner:
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
# Test 1 — DockerRunner.run_simple raises SubprocessTimeoutError on timeout
# ---------------------------------------------------------------------------


class TestDockerRunSimpleTimeoutContract:
    """Docker-mode timeouts must raise SubprocessTimeoutError, not raw TimeoutError."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6959 — fix not yet landed", strict=False)
    async def test_run_simple_raises_subprocess_timeout_error(
        self, tmp_path: Path
    ) -> None:
        """When a Docker container exceeds its timeout, ``run_simple`` must
        raise ``SubprocessTimeoutError`` so callers using
        ``except SubprocessTimeoutError`` handle it correctly.

        Currently raises raw ``TimeoutError`` — this test is RED until the
        exception is translated.
        """
        container = _make_mock_container()
        client = _make_mock_docker_client(container)
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        runner = _make_runner(mock_client=client, log_dir=log_dir)

        with (
            patch("asyncio.wait_for", side_effect=TimeoutError),
            pytest.raises(SubprocessTimeoutError),
        ):
            await runner.run_simple(["sleep", "999"], timeout=0.01)

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6959 — fix not yet landed", strict=False)
    async def test_timeout_exception_is_chained(self, tmp_path: Path) -> None:
        """The ``SubprocessTimeoutError`` must chain the original ``TimeoutError``
        via ``from exc`` so the traceback preserves the root cause.

        Currently the bare ``raise`` drops the chain entirely — this test is
        RED until ``raise SubprocessTimeoutError(...) from exc`` is used.
        """
        container = _make_mock_container()
        client = _make_mock_docker_client(container)
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        runner = _make_runner(mock_client=client, log_dir=log_dir)

        with patch("asyncio.wait_for", side_effect=TimeoutError("timed out")):
            try:
                await runner.run_simple(["sleep", "999"], timeout=0.01)
                pytest.fail("Expected SubprocessTimeoutError was not raised")
            except SubprocessTimeoutError as exc:
                assert exc.__cause__ is not None, (
                    "SubprocessTimeoutError must be chained with 'from exc' "
                    "to preserve the original TimeoutError"
                )
                assert isinstance(exc.__cause__, TimeoutError)
            except TimeoutError:
                pytest.fail(
                    "run_simple raised raw TimeoutError instead of "
                    "SubprocessTimeoutError — inconsistent timeout contract "
                    "(issue #6959)"
                )


# ---------------------------------------------------------------------------
# Test 2 — except SubprocessTimeoutError guard misses Docker timeouts
# ---------------------------------------------------------------------------


class TestCallerSubprocessTimeoutGuard:
    """Callers guarding with ``except SubprocessTimeoutError`` must catch
    Docker-mode timeouts — currently they silently miss them."""

    @pytest.mark.asyncio
    @pytest.mark.xfail(reason="Regression for issue #6959 — fix not yet landed", strict=False)
    async def test_except_subprocess_timeout_error_catches_docker_timeout(
        self, tmp_path: Path
    ) -> None:
        """Simulate a caller that catches ``SubprocessTimeoutError``.

        With the bug present, the Docker timeout escapes as a raw
        ``TimeoutError`` and the handler never fires.
        """
        container = _make_mock_container()
        client = _make_mock_docker_client(container)
        log_dir = tmp_path / "logs"
        log_dir.mkdir(parents=True)
        runner = _make_runner(mock_client=client, log_dir=log_dir)

        caught = False

        with patch("asyncio.wait_for", side_effect=TimeoutError):
            try:
                await runner.run_simple(["sleep", "999"], timeout=1.0)
            except SubprocessTimeoutError:
                caught = True
            except TimeoutError:
                pass  # Bug: this path fires instead

        assert caught, (
            "Docker timeout was not caught by 'except SubprocessTimeoutError' — "
            "raw TimeoutError escaped instead, breaking the unified timeout "
            "contract (issue #6959)"
        )
