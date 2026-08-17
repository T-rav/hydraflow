"""Tests for the #11219 host-wide quality lock."""

from __future__ import annotations

import os
import subprocess  # nosec B404 - exercises the wrapper script itself
import sys
import time
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "quality_host_lock.py"


def _run(
    *command: str, env: dict[str, str] | None = None
) -> subprocess.CompletedProcess:
    full_env = {**os.environ, **(env or {})}
    return subprocess.run(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", *command],
        capture_output=True,
        text=True,
        env=full_env,
        check=False,
    )


def test_runs_the_command_and_propagates_success(tmp_path: Path) -> None:
    result = _run("echo", "hello", env={"TMPDIR": str(tmp_path)})
    assert result.returncode == 0
    assert "hello" in result.stdout


def test_propagates_a_failing_exit_code(tmp_path: Path) -> None:
    result = _run("sh", "-c", "exit 7", env={"TMPDIR": str(tmp_path)})
    assert result.returncode == 7


def test_second_run_waits_for_the_first(tmp_path: Path) -> None:
    """The core contract: concurrent suites queue instead of racing."""
    env = {"TMPDIR": str(tmp_path)}
    holder = subprocess.Popen(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", "sleep", "3"],
        env={**os.environ, **env},
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.8)  # let the holder acquire
    started = time.monotonic()
    second = _run("echo", "second", env=env)
    waited = time.monotonic() - started
    holder.wait(timeout=30)
    assert second.returncode == 0
    assert "second" in second.stdout
    # It waited for the holder rather than running concurrently.
    assert waited >= 1.5
    assert "waiting" in second.stdout


def test_disable_flag_bypasses_the_lock(tmp_path: Path) -> None:
    env = {"TMPDIR": str(tmp_path), "HYDRAFLOW_QUALITY_LOCK_DISABLE": "1"}
    holder = subprocess.Popen(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", "sleep", "3"],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.8)
    started = time.monotonic()
    result = _run("echo", "bypassed", env=env)
    elapsed = time.monotonic() - started
    holder.wait(timeout=30)
    assert result.returncode == 0
    assert elapsed < 1.5  # did not wait


def test_timeout_runs_anyway_rather_than_failing(tmp_path: Path) -> None:
    """The lock is advisory: a stuck holder must not block work forever."""
    env = {"TMPDIR": str(tmp_path), "HYDRAFLOW_QUALITY_LOCK_TIMEOUT": "1"}
    holder = subprocess.Popen(  # nosec B603
        [sys.executable, str(_SCRIPT), "--", "sleep", "6"],
        env={**os.environ, "TMPDIR": str(tmp_path)},
        stdout=subprocess.PIPE,
        text=True,
    )
    time.sleep(0.8)
    result = _run("echo", "ran-anyway", env=env)
    holder.wait(timeout=30)
    assert result.returncode == 0
    assert "ran-anyway" in result.stdout
    assert "running anyway" in result.stdout


def test_usage_error_without_separator(tmp_path: Path) -> None:
    result = subprocess.run(  # nosec B603
        [sys.executable, str(_SCRIPT), "echo", "x"],
        capture_output=True,
        text=True,
        check=False,
    )
    assert result.returncode == 2
