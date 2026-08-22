"""Implement spawn's quality gate stays off the host lock (#11568) — MockWorld.

Drives the real ``AgentRunner`` through ``FakeSubprocessRunner``: ``git`` runs
on the host (real worktree commits) and every ``make`` argv is recorded by
``FakeDocker.invocations``. The implement path must never spawn the
host-locked ``make quality`` (``scripts/quality_host_lock.py``, #11400): it
runs ``make quality-lite`` then the bounded impacted-test target, and the
quality-fix loop re-verifies through the same lock-free steps.
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario

_OK = [{"type": "result", "success": True, "exit_code": 0}]
_FAIL = [{"type": "result", "success": False, "exit_code": 1}]
# A HydraFlow-shaped Makefile: the gate probes it for ``test-impacted``.
_MAKEFILE = "quality-lite:\n\t@true\ntest:\n\t@true\ntest-impacted: deps\n\t@true\n"


def _make_commands(world: MockWorld) -> list[list[str]]:
    return [
        inv.command for inv in world.docker.invocations if inv.command[:1] == ["make"]
    ]


def _assert_off_host_lock(commands: list[list[str]]) -> None:
    assert ["make", "quality"] not in commands, commands
    assert not any("quality_host_lock" in " ".join(c) for c in commands), commands


async def test_implement_gate_runs_quality_lite_then_bounded_impacted_tests(
    tmp_path,
) -> None:
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("x.py", "changed"), ("Makefile", _MAKEFILE)],
        cwd=worktree_cwd,
    )

    result = await world.run_pipeline()

    assert result.issue(1).merged, result.issue(1)
    commands = _make_commands(world)
    _assert_off_host_lock(commands)
    assert ["make", "quality-lite"] in commands, commands
    impacted = [c for c in commands if c[:2] == ["make", "test-impacted"]]
    assert len(impacted) == 1, commands
    assert "IMPACTED_ARGS=--bounded" in impacted[0]
    assert any(arg.startswith("BASE_REF=origin/") for arg in impacted[0])
    assert commands.index(["make", "quality-lite"]) < commands.index(impacted[0])


async def test_quality_fix_loop_reverifies_without_the_host_lock(tmp_path) -> None:
    """quality-lite fails -> fix agent -> quality-lite passes -> impacted tests pass.

    FakeDocker scripts are FIFO across streaming and ``run_simple`` calls
    (see ``test_agent_realistic.test_A10_*`` for the slot accounting): one
    agent run, the post-implementation skills (three agent calls plus
    test-adequacy's ``make coverage`` probe), the pre-quality review pair,
    then the gate. The gate's first step is scripted red so the production
    ``_run_quality_fix_loop`` runs; its re-verification must take the same
    lock-free path, never ``make quality``.
    """
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    # 1) agent run: commits broken code (+ the Makefile the gate probes)
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("x.py", "broken"), ("Makefile", _MAKEFILE)],
        cwd=worktree_cwd,
    )
    # 2-5) post-implementation skills: diff-sanity, scope-check, test-adequacy
    #      (+ its ``make coverage 0`` probe, also a FakeDocker slot) — success
    for _ in range(4):
        world.docker.script_run(_OK)
    # 6-7) pre-quality review + run-tool — default success
    world.docker.script_run(_OK)
    world.docker.script_run(_OK)
    # 8) make quality-lite — FAILS
    world.docker.script_run(_FAIL)
    # 9) quality-fix agent: commits the fix
    world.docker.script_run_with_commits(
        events=_OK, commits=[("x.py", "fixed")], cwd=worktree_cwd
    )
    # 10-11) make quality-lite, then make test-impacted — both pass
    world.docker.script_run(_OK)
    world.docker.script_run(_OK)

    result = await world.run_pipeline()

    assert result.issue(1).merged, result.issue(1)
    commands = _make_commands(world)
    _assert_off_host_lock(commands)
    assert commands.count(["make", "quality-lite"]) == 2, commands
    assert sum(1 for c in commands if c[:2] == ["make", "test-impacted"]) == 1, commands
    worker_result = result.issue(1).worker_result
    assert worker_result is not None
    assert worker_result.quality_fix_attempts == 1
