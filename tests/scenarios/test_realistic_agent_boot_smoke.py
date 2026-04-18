"""Anti-drift canary — fails loud if AgentRunner/config API drifts.

If production code renames required config fields, moves AgentRunner.run,
or changes the SubprocessRunner protocol, this test is the first signal —
before it hides inside a scenario-test failure.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.scenarios.fakes.mock_world import MockWorld

pytestmark = pytest.mark.scenario


def _init_test_worktree(path: Path, *, branch: str = "agent/issue-1") -> None:
    """Prepare *path* as a git repo suitable for scenario testing.

    Sets up:
    - A bare ``origin.git`` sibling directory used as the remote.
    - An initial commit on ``main`` (so ``origin/main`` is reachable).
    - The working branch *branch* checked out and pushed to origin.

    After this function returns, ``git rev-list --count origin/main..{branch}``
    will return ``"0"`` until a new commit is added on *branch*.
    """
    path.mkdir(parents=True, exist_ok=True)
    origin = path.parent / "origin.git"
    origin.mkdir(parents=True, exist_ok=True)

    run = lambda *args, cwd=path: subprocess.run(  # noqa: E731
        list(args), cwd=cwd, check=True, capture_output=True
    )

    # Bare origin
    subprocess.run(
        ["git", "init", "--bare", str(origin)],
        check=True,
        capture_output=True,
    )

    # Worktree
    run("git", "init", "-b", "main")
    run("git", "config", "user.email", "test@test")
    run("git", "config", "user.name", "test")
    run("git", "commit", "--allow-empty", "-m", "init")
    run("git", "remote", "add", "origin", str(origin))
    run("git", "push", "-u", "origin", "main")

    # Create and push the feature branch
    run("git", "checkout", "-b", branch)
    run("git", "push", "-u", "origin", branch)


async def test_real_agent_runner_single_event_smoke(tmp_path) -> None:
    """Single realistic-agent invocation proves the wiring stack boots."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    _init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=[
            {"type": "tool_use", "name": "edit_file", "input": {"path": "x"}},
            {"type": "message", "text": "done"},
            {"type": "result", "success": True, "exit_code": 0},
        ],
        commits=[("x.py", "content")],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    # The real AgentRunner ran end-to-end. Docker saw at least one invocation.
    # Exact count may include pre-quality review loop retries — the contract
    # here is "implement phase ran", not "ran exactly once".
    assert len(world.docker.invocations) >= 1
    assert result.issue(1).worker_result is not None
