"""Regression: force-commit salvage must survive slow pre-commit hooks (#10598).

``AgentRunner._force_commit_uncommitted`` salvages the work an agent left
uncommitted by running ``git add -A`` + ``git commit``. The salvage commit
runs the repo's **pre-commit hook** (quality-lite / security / arch-check —
which we must NOT ``--no-verify``), and that hook routinely exceeds the 30s
``git_command_timeout`` short tier. Before the fix the commit shared that
30s budget, so it hit ``TimeoutError`` and the agent's real changes were
discarded → zero commits. Worse, ``str(TimeoutError())`` is empty, so the
warning read ``force-commit failed:`` with no reason.

The fix gives the salvage ``git commit`` a hook-aware (make-tier) timeout
while keeping ``git status`` / ``git add`` on the short git tier, and logs an
explicit, non-empty duration when a git command genuinely times out.
"""

from __future__ import annotations

import logging
import sys
from collections.abc import Sequence
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent.parent / "src"))

import pytest

import execution
from agent import AgentRunner
from events import EventBus
from execution import SimpleResult
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


class _SlowHookHost:
    """Fake host runner where ``git commit`` runs a >30s pre-commit hook.

    The commit only completes when handed a timeout longer than the short
    git tier; on the short tier it raises ``TimeoutError`` (exactly as the
    real hook does when it blows past ``git_command_timeout``).
    """

    def __init__(self, git_tier: int, *, commit_always_times_out: bool = False) -> None:
        self._git_tier = git_tier
        self._commit_always_times_out = commit_always_times_out
        self.calls: list[tuple[list[str], float]] = []

    async def run_simple(
        self,
        cmd: Sequence[str],
        *,
        cwd: str | None = None,
        timeout: float = 120.0,
        **_kwargs: object,
    ) -> SimpleResult:
        cmd = list(cmd)
        self.calls.append((cmd, timeout))
        head = cmd[:2]
        if head == ["git", "status"]:
            return SimpleResult(stdout=" M src/foo.py\n")
        if head == ["git", "add"]:
            return SimpleResult()
        if head == ["git", "commit"]:
            if self._commit_always_times_out or timeout <= self._git_tier:
                raise TimeoutError
            return SimpleResult()
        return SimpleResult()

    def commit_timeout(self) -> float | None:
        for cmd, timeout in self.calls:
            if cmd[:2] == ["git", "commit"]:
                return timeout
        return None


def _make_runner() -> AgentRunner:
    config = ConfigFactory.create()
    return AgentRunner(config, EventBus())


@pytest.mark.asyncio
async def test_slow_precommit_hook_still_yields_salvage_commit(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """A salvage commit whose pre-commit hook exceeds the 30s git tier still lands."""
    runner = _make_runner()
    host = _SlowHookHost(git_tier=runner._config.git_command_timeout)
    monkeypatch.setattr(execution, "get_default_runner", lambda: host)

    task = TaskFactory.create()
    committed = await runner._force_commit_uncommitted(task, tmp_path)

    assert committed is True, "slow-hook salvage commit must not be discarded"
    # The commit ran on a generous (make-tier) budget, not the 30s git tier.
    assert host.commit_timeout() is not None
    assert host.commit_timeout() > runner._config.git_command_timeout


@pytest.mark.asyncio
async def test_timed_out_git_command_logs_nonempty_duration_reason(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    """A genuinely timing-out git command logs an explicit, non-empty duration."""
    runner = _make_runner()
    host = _SlowHookHost(
        git_tier=runner._config.git_command_timeout,
        commit_always_times_out=True,
    )
    monkeypatch.setattr(execution, "get_default_runner", lambda: host)

    task = TaskFactory.create()
    with caplog.at_level(logging.WARNING):
        committed = await runner._force_commit_uncommitted(task, tmp_path)

    assert committed is False
    reasons = [
        r.getMessage()
        for r in caplog.records
        if "force-commit failed" in r.getMessage()
    ]
    assert reasons, "a timeout must still log a force-commit failure"
    reason = reasons[-1]
    # The bug: str(TimeoutError()) is empty -> "force-commit failed:" with no cause.
    assert reason.rstrip().endswith(":") is False, f"empty timeout reason: {reason!r}"
    assert "timed out" in reason
    # The duration (the make-tier commit budget) is named so the cause is visible.
    assert str(runner._config.salvage_commit_timeout) in reason


def test_salvage_commit_timeout_is_hook_aware_make_tier() -> None:
    """The salvage commit budget is a make-tier timeout, well above the git tier."""
    config = ConfigFactory.create()
    assert config.salvage_commit_timeout >= 1800
    assert config.salvage_commit_timeout > config.git_command_timeout
