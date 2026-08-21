"""Test-adequacy gate repairs in-run before rejecting (#11593) — MockWorld.

Drives the real ``AgentRunner`` through ``FakeSubprocessRunner``: the finder
rejects the branch with concrete gaps, ONE bounded repair pass hands those
findings back to the implementer worktree (a scripted commit adds the missing
test, so HEAD moves), and the FULL re-check — finder, ``make coverage`` probe,
independent verifier — passes. The run that died with ``test-adequacy
failed: …`` before #11593 now merges, and the rejection telemetry records the
rescue.

FakeDocker FIFO (scripts are consumed by ALL calls in order; git runs on the
host against the real worktree and consumes no slots):

  1. Initial agent _execute (streaming) — commits code
  2. diff-sanity skill _execute — default success (no marker)
  3. scope-check skill _execute — default success
     (plan-compliance is skipped: empty prompt with no plan)
  4. test-adequacy finder _execute — EXPLICIT RETRY with GAPS
  5. REPAIR _execute — commits the missing test (HEAD moves)  ← #11593
  6. re-check finder _execute — EXPLICIT OK
  7. ``make coverage 0`` — exit 0, no coverage.xml → pass preserved
  8. independent verifier _execute — CONCUR keeps the pass
  9+. pre-quality review / run-tool / implement gate — default success
      (script queue exhausted → FakeDocker default-OK)
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario

_OK = [{"type": "result", "success": True, "exit_code": 0}]


def _text_events(text: str) -> list[dict]:
    return [
        {
            "type": "assistant",
            "message": {"id": "m1", "content": [{"type": "text", "text": text}]},
        },
        {"type": "result", "success": True, "exit_code": 0},
    ]


async def test_adequacy_rejection_is_repaired_in_run_and_the_issue_merges(
    tmp_path,
) -> None:
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    # 1) Initial agent run: commits production code without tests
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("x.py", "def frob(): return 1\n")],
        cwd=worktree_cwd,
    )
    # 2–3) diff-sanity + scope-check — default success
    world.docker.script_run(_OK)
    world.docker.script_run(_OK)
    # 4) test-adequacy finder — EXPLICIT RETRY with a concrete gap
    world.docker.script_run(
        _text_events(
            "TEST_ADEQUACY_RESULT: RETRY\n"
            "SUMMARY: missing tests\n"
            "GAPS:\n"
            "- x.py:frob — no test\n"
        )
    )
    # 5) REPAIR pass (#11593): the implementer writes exactly the missing test
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("test_x.py", "def test_frob(): assert True\n")],
        cwd=worktree_cwd,
    )
    # 6) re-check finder — EXPLICIT OK (triggers the verifier)
    world.docker.script_run(
        _text_events("TEST_ADEQUACY_RESULT: OK\nSUMMARY: coverage adequate")
    )
    # 7) make coverage 0 — exit 0, no coverage.xml (graceful preserve)
    world.docker.script_run(_OK)
    # 8) independent verifier — CONCUR keeps the repaired pass
    world.docker.script_run(
        _text_events(
            "TEST_ADEQUACY_VERIFIER_RESULT: CONCUR\nSUMMARY: independently confirmed"
        )
    )
    # 9+) pre-quality review / run-tool / gate — FakeDocker default-OK

    result = await world.run_pipeline()

    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )
    repair_invs = [
        inv
        for inv in world.docker.invocations
        if any("Test Adequacy REPAIR pass" in arg for arg in inv.command)
    ]
    assert len(repair_invs) == 1, (
        f"expected exactly 1 repair dispatch, got {len(repair_invs)}; "
        f"commands={[' '.join(i.command)[:80] for i in world.docker.invocations]}"
    )
    worker_result = result.issue(1).worker_result
    assert worker_result is not None and worker_result.test_adequacy is not None


async def test_repair_telemetry_records_the_rescue(tmp_path) -> None:
    """Seam 3: the rescued run carries the verdict-flipped repair record."""
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    worktree_cwd = tmp_path / "worktrees" / "issue-1"
    init_test_worktree(worktree_cwd)

    world.docker.script_run_with_commits(
        events=_OK, commits=[("x.py", "def frob(): return 1\n")], cwd=worktree_cwd
    )
    world.docker.script_run(_OK)
    world.docker.script_run(_OK)
    world.docker.script_run(
        _text_events(
            "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: missing tests\n"
            "GAPS:\n- x.py:frob — no test\n"
        )
    )
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("test_x.py", "def test_frob(): assert True\n")],
        cwd=worktree_cwd,
    )
    world.docker.script_run(
        _text_events("TEST_ADEQUACY_RESULT: OK\nSUMMARY: coverage adequate")
    )
    world.docker.script_run(_OK)
    world.docker.script_run(
        _text_events(
            "TEST_ADEQUACY_VERIFIER_RESULT: CONCUR\nSUMMARY: independently confirmed"
        )
    )

    result = await world.run_pipeline()

    telemetry = result.issue(1).worker_result.test_adequacy
    assert telemetry.repair_outcomes == ["verdict-flipped"]
    assert telemetry.passed is True
    assert telemetry.repair_passes_used == 1
