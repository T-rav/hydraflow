"""Anti-drift canary — fails loud if AgentRunner/config API drifts.

If production code renames required config fields, moves AgentRunner.run,
or changes the SubprocessRunner protocol, this test is the first signal —
before it hides inside a scenario-test failure.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario


async def test_real_agent_runner_single_event_smoke(tmp_path) -> None:
    """Single realistic-agent invocation proves the wiring stack boots."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])

    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

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
