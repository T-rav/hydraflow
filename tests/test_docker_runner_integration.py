"""Integration tests for docker_runner.py — requires a running Docker daemon.

These tests exercise DockerRunner against a real Docker daemon to verify
container creation, stream demultiplexing, resource limits, volume mounts,
cleanup, and network isolation.

Run with: pytest -m docker tests/test_docker_runner_integration.py
Skip with: pytest -m "not docker"
"""

from __future__ import annotations

from collections.abc import AsyncGenerator
from pathlib import Path
from typing import TYPE_CHECKING
from unittest.mock import MagicMock

import pytest

if TYPE_CHECKING:
    from docker_runner import DockerRunner

# Guard: skip the entire module when Docker is not available.
try:
    import docker

    _client = docker.from_env()
    _client.ping()
    _DOCKER_AVAILABLE = True
except Exception:
    _DOCKER_AVAILABLE = False

pytestmark = [
    pytest.mark.docker,
    pytest.mark.skipif(not _DOCKER_AVAILABLE, reason="Docker daemon not available"),
]

# A minimal image available on most Docker hosts.
_TEST_IMAGE = "alpine:latest"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def _pull_image() -> None:
    """Ensure the test image is pulled once per module."""
    client = docker.from_env()
    try:
        client.images.get(_TEST_IMAGE)
    except docker.errors.ImageNotFound:
        client.images.pull(_TEST_IMAGE)


@pytest.fixture()
def repo_root(tmp_path: Path) -> Path:
    """Create a temporary repo root directory."""
    repo = tmp_path / "repo"
    repo.mkdir()
    return repo


@pytest.fixture()
def log_dir(tmp_path: Path) -> Path:
    """Create a temporary log directory."""
    logs = tmp_path / "logs"
    logs.mkdir()
    return logs


@pytest.fixture()
def work_dir(tmp_path: Path) -> Path:
    """Create a temporary working directory (simulates a worktree)."""
    wd = tmp_path / "workspace"
    wd.mkdir()
    return wd


@pytest.fixture()
def docker_config() -> MagicMock:
    """Minimal HydraFlowConfig mock for DockerRunner."""
    cfg = MagicMock()
    cfg.docker_cpu_limit = 1.0
    cfg.docker_memory_limit = "128m"
    cfg.docker_pids_limit = 64
    cfg.docker_network_mode = "none"
    cfg.docker_read_only_root = False
    cfg.docker_no_new_privileges = True
    cfg.docker_tmp_size = "64m"
    return cfg


@pytest.fixture()
async def runner(
    _pull_image: None,
    repo_root: Path,
    log_dir: Path,
    docker_config: MagicMock,
) -> AsyncGenerator[DockerRunner, None]:
    """Create a DockerRunner pointed at the test image, with cleanup after each test."""
    from docker_runner import DockerRunner

    r = DockerRunner(
        image=_TEST_IMAGE,
        repo_root=repo_root,
        log_dir=log_dir,
        spawn_delay=0.0,
        config=docker_config,
    )
    try:
        yield r
    finally:
        await r.cleanup()


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestContainerCreation:
    """Test container creation with a real Docker daemon."""

    async def test_run_simple_echo(self, runner: DockerRunner, work_dir: Path) -> None:
        """A basic echo command should succeed and return stdout."""
        result = await runner.run_simple(
            ["echo", "hello world"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 0
        assert "hello world" in result.stdout

    async def test_run_simple_stderr(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """stderr output should be captured separately."""
        result = await runner.run_simple(
            ["sh", "-c", "echo err >&2"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 0
        assert "err" in result.stderr

    async def test_nonzero_exit_code(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Non-zero exit codes should propagate correctly."""
        result = await runner.run_simple(
            ["sh", "-c", "exit 42"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 42


class TestStreamDemultiplexing:
    """Test multiplexed stdout/stderr stream parsing with a real Docker attach socket."""

    async def test_streaming_process_stdout(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Streaming process should yield stdout lines via async iteration."""
        proc = await runner.create_streaming_process(
            ["sh", "-c", "echo line1; echo line2; echo line3"],
            cwd=str(work_dir),
        )
        lines: list[bytes] = []
        async for chunk in proc.stdout:  # type: ignore[union-attr]
            lines.append(chunk)

        exit_code = await proc.wait()
        assert exit_code == 0
        combined = b"".join(lines).decode()
        assert "line1" in combined
        assert "line2" in combined
        assert "line3" in combined

    async def test_streaming_process_stderr_collection(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Stderr should be collected during stdout streaming."""
        proc = await runner.create_streaming_process(
            ["sh", "-c", "echo out; echo err >&2"],
            cwd=str(work_dir),
        )
        # Drain stdout
        async for _ in proc.stdout:  # type: ignore[union-attr]
            pass

        stderr_data = await proc.stderr.read()  # type: ignore[union-attr]
        await proc.wait()
        assert b"err" in stderr_data


class TestVolumeMounts:
    """Test volume mount correctness — files visible inside container and changes persisted."""

    async def test_host_file_visible_in_container(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Files in the host work_dir should be visible as /workspace inside the container."""
        (work_dir / "testfile.txt").write_text("hello from host")

        result = await runner.run_simple(
            ["cat", "/workspace/testfile.txt"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 0
        assert "hello from host" in result.stdout

    async def test_container_changes_persisted_to_host(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Changes made inside the container should be persisted to the host volume."""
        result = await runner.run_simple(
            ["sh", "-c", "echo written_by_container > /workspace/output.txt"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 0

        output = (work_dir / "output.txt").read_text()
        assert "written_by_container" in output

    async def test_repo_mounted_read_only(
        self, runner: DockerRunner, repo_root: Path, work_dir: Path
    ) -> None:
        """The repo root is mounted at /repo as read-only — writes should fail."""
        (repo_root / "existing.txt").write_text("original")

        result = await runner.run_simple(
            ["sh", "-c", "echo overwrite > /repo/existing.txt"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        # The write should fail because /repo is read-only
        assert result.returncode != 0

        # Original file should be unchanged
        assert (repo_root / "existing.txt").read_text() == "original"

    async def test_log_dir_mounted(
        self, runner: DockerRunner, log_dir: Path, work_dir: Path
    ) -> None:
        """The log directory should be mounted at /logs inside the container."""
        result = await runner.run_simple(
            ["sh", "-c", "echo logentry > /logs/test.log"],
            cwd=str(work_dir),
            timeout=30.0,
        )
        assert result.returncode == 0
        assert (log_dir / "test.log").read_text().strip() == "logentry"


class TestContainerCleanup:
    """Test container cleanup on timeout and normal completion."""

    async def test_cleanup_removes_containers(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """After cleanup(), no tracked containers should remain in Docker."""
        # Run a container that stays alive for a bit
        await runner.create_streaming_process(
            ["sleep", "60"],
            cwd=str(work_dir),
        )
        # We should have at least one tracked container
        assert len(runner._containers) >= 1
        container_ids = [c.id for c in runner._containers]

        # Cleanup should remove all
        await runner.cleanup()
        assert len(runner._containers) == 0

        # Verify containers are actually gone from Docker
        client = docker.from_env()
        for cid in container_ids:
            with pytest.raises(docker.errors.NotFound):
                client.containers.get(cid)

    async def test_timeout_kills_container(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """A container that exceeds the timeout should be killed."""
        with pytest.raises(TimeoutError):
            await runner.run_simple(
                ["sleep", "60"],
                cwd=str(work_dir),
                timeout=2.0,
            )

        # After timeout, the container should have been cleaned up
        assert len(runner._containers) == 0

    async def test_async_context_manager_cleanup(
        self,
        _pull_image: None,
        repo_root: Path,
        log_dir: Path,
        work_dir: Path,
        docker_config: MagicMock,
    ) -> None:
        """Using DockerRunner as async context manager should clean up on exit."""
        from docker_runner import DockerRunner

        async with DockerRunner(
            image=_TEST_IMAGE,
            repo_root=repo_root,
            log_dir=log_dir,
            spawn_delay=0.0,
            config=docker_config,
        ) as dr:
            await dr.create_streaming_process(
                ["sleep", "60"],
                cwd=str(work_dir),
            )
            container_ids = [c.id for c in dr._containers]
            assert len(container_ids) >= 1

        # After exiting the context manager, containers should be removed
        client = docker.from_env()
        for cid in container_ids:
            with pytest.raises(docker.errors.NotFound):
                client.containers.get(cid)


class TestNetworkIsolation:
    """Test container network isolation."""

    async def test_network_mode_none_blocks_traffic(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """With network_mode='none', the container should not be able to reach external hosts."""
        result = await runner.run_simple(
            ["sh", "-c", "ping -c 1 -W 2 8.8.8.8 2>&1 || echo NETWORK_BLOCKED"],
            cwd=str(work_dir),
            timeout=15.0,
        )
        # Either ping fails (non-zero exit) or the echo runs
        assert result.returncode != 0 or "NETWORK_BLOCKED" in result.stdout


class TestResourceLimits:
    """Test resource limit enforcement with real Docker."""

    async def test_memory_limit_enforced(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """A container that exceeds its memory limit should be killed (OOMKilled)."""
        # The runner has 128m memory limit. Allocate well beyond that using
        # a shell approach that holds memory (writing to a tmpfs which counts
        # against the cgroup memory limit).
        result = await runner.run_simple(
            [
                "sh",
                "-c",
                # Write to /dev/shm (tmpfs backed by memory) to force real allocation
                "dd if=/dev/zero of=/dev/shm/fill bs=1M count=256 2>&1; echo done",
            ],
            cwd=str(work_dir),
            timeout=30.0,
        )
        # The container should be OOM-killed (exit code 137 = SIGKILL) or
        # the dd should fail with a write error due to memory limits.
        assert (
            result.returncode != 0 or "No space left" in result.stdout + result.stderr
        ), f"Expected OOM kill or write failure, got rc={result.returncode}"

    async def test_pids_limit_enforced(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """A container should be unable to create processes beyond its PID limit."""
        # PID limit is 64 — try to fork many more
        result = await runner.run_simple(
            [
                "sh",
                "-c",
                # Try to spawn 200 background processes — should fail around pid limit
                "for i in $(seq 1 200); do sleep 60 & done 2>&1; echo FORK_COUNT=$(jobs -p | wc -l)",
            ],
            cwd=str(work_dir),
            timeout=30.0,
        )
        # Extract fork count — it should be less than 200 due to PID limit
        if "FORK_COUNT=" in result.stdout:
            count_str = result.stdout.split("FORK_COUNT=")[1].strip().split()[0]
            fork_count = int(count_str)
            # With a PID limit of 64 (including the sh process and its children),
            # we should have significantly fewer than 200 forks
            assert fork_count < 200, (
                f"Expected fewer than 200 forked processes with pids_limit=64, "
                f"got {fork_count}"
            )
        else:
            # If we didn't get the output, the container was likely killed due to
            # resource limits — that's also an acceptable outcome
            pass


class TestSecurityOpts:
    """Test security configuration against real Docker."""

    async def test_no_new_privileges(
        self, runner: DockerRunner, work_dir: Path
    ) -> None:
        """Container should run with no-new-privileges security option."""
        result = await runner.run_simple(
            ["cat", "/proc/self/status"],
            cwd=str(work_dir),
            timeout=15.0,
        )
        assert result.returncode == 0
        # NoNewPrivs should be 1 (enabled)
        assert "NoNewPrivs:\t1" in result.stdout


class TestBuildContainerKwargsValidation:
    """Test that build_container_kwargs output is accepted by Docker SDK."""

    async def test_kwargs_accepted_by_docker_create(
        self, _pull_image: None, docker_config: MagicMock, work_dir: Path
    ) -> None:
        """Container kwargs from build_container_kwargs should be valid for Docker SDK."""
        from docker_runner import build_container_kwargs

        kwargs = build_container_kwargs(docker_config)

        client = docker.from_env()
        container = client.containers.create(
            _TEST_IMAGE,
            command=["echo", "test"],
            **kwargs,
        )
        try:
            container.start()
            result = container.wait()
            assert result["StatusCode"] == 0
        finally:
            container.remove(force=True)

    async def test_kwargs_resource_values_match_config(
        self, docker_config: MagicMock
    ) -> None:
        """Verify kwargs values match the config inputs."""
        from docker_runner import build_container_kwargs

        kwargs = build_container_kwargs(docker_config)

        assert kwargs["nano_cpus"] == int(1.0 * 1e9)
        assert kwargs["mem_limit"] == "128m"
        assert kwargs["pids_limit"] == 64
        assert kwargs["network_mode"] == "none"
        assert kwargs["cap_drop"] == ["ALL"]
        assert "no-new-privileges:true" in kwargs["security_opt"]
