"""Pinned test-adequacy demand across retries (#11644) — MockWorld.

Drives the real ``AgentRunner`` and the real ``ImplementPhase`` retry seam
through ``FakeSubprocessRunner``. A previous attempt died at the adequacy gate
demanding one concrete, anchored gap; that demand is pinned in the worker-result
metadata exactly as ``_record_impl_metrics`` writes it. This attempt closes it,
and the finder comes back with a *different*, entirely unlocatable gap — the
0.04-overlap pathology #11643 measured over 15 hand-read re-rejection pairs.

Before #11644 that second demand burned the attempt. Here the run clears the
gate on the demand it was actually given, and the absorbed finding is recorded
so the moving bar stays visible in telemetry rather than disappearing.

FakeDocker FIFO (scripts are consumed by ALL calls in order; git runs on the
host against the real worktree and consumes no slots):

  1. Initial agent _execute (streaming) — commits code
  2. diff-sanity skill _execute — default success (no marker)
  3. scope-check skill _execute — default success
     (plan-compliance is skipped: empty prompt with no plan)
  4. test-adequacy finder _execute — RETRY naming a NEW, UNANCHORED gap
     → the pinned demand is closed, so the contract records it as advisory
  5. ``make coverage 0`` — exit 0, no coverage.xml → the pass is preserved
     (the independent verifier does NOT run: it triggers only on an explicit
     ``TEST_ADEQUACY_RESULT: OK`` marker, and this transcript says RETRY)
  6+. pre-quality review / run-tool / implement gate — FakeDocker default-OK
"""

from __future__ import annotations

import pytest

from tests.scenarios.fakes.mock_world import MockWorld
from tests.scenarios.helpers.git_worktree_fixture import init_test_worktree

pytestmark = pytest.mark.scenario

_OK = [{"type": "result", "success": True, "exit_code": 0}]

#: The demand the previous attempt stated — anchored, and now closed.
_PINNED = ["src/frobnicator.py:rebuild_index — no test for the failure branch"]

#: What the finder comes back with instead: new, and naming nothing locatable.
_NEW_UNANCHORED = (
    "TEST_ADEQUACY_RESULT: RETRY\nSUMMARY: boundary-condition gap in truncation logic\n"
)


def _text_events(text: str) -> list[dict]:
    return [
        {
            "type": "assistant",
            "message": {"id": "m1", "content": [{"type": "text", "text": text}]},
        },
        {"type": "result", "success": True, "exit_code": 0},
    ]


def _world_with_a_pinned_demand(tmp_path) -> MockWorld:
    world = MockWorld(tmp_path, use_real_agent_runner=True)
    world.add_issue(1, "t", "b", labels=["hydraflow-ready"])
    init_test_worktree(tmp_path / "worktrees" / "issue-1")
    # Exactly what _record_impl_metrics writes after a gate rejection.
    world.harness.state.set_worker_result_meta(
        1,
        {
            "pre_quality_review_attempts": 0,
            "duration_seconds": 1740.0,
            "error": "test-adequacy failed: missing tests",
            "commits": 1,
            "test_adequacy_findings": _PINNED,
        },
    )
    world.docker.script_run_with_commits(
        events=_OK,
        commits=[("x.py", "def frob(): return 1\n")],
        cwd=tmp_path / "worktrees" / "issue-1",
    )
    world.docker.script_run(_OK)
    world.docker.script_run(_OK)
    world.docker.script_run(_text_events(_NEW_UNANCHORED))
    world.docker.script_run(_OK)
    return world


async def test_a_retry_that_closed_the_pinned_demand_merges(tmp_path) -> None:
    world = _world_with_a_pinned_demand(tmp_path)

    result = await world.run_pipeline()

    assert result.issue(1).merged, (
        f"expected merged=True; outcome={result.issue(1)!r}; "
        f"docker_invocations={len(world.docker.invocations)}"
    )


async def test_the_absorbed_demand_is_recorded_in_the_telemetry(tmp_path) -> None:
    """The moving bar stays measurable — the fix must not hide what it absorbs."""
    world = _world_with_a_pinned_demand(tmp_path)

    result = await world.run_pipeline()

    telemetry = result.issue(1).worker_result.test_adequacy
    assert telemetry.advisory_findings == ["boundary-condition gap in truncation logic"]
