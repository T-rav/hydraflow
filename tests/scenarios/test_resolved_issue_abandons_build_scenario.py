"""MockWorld scenario — a resolved issue is abandoned before the build (#11457).

The regression shape of #11443/#11451: the work-picker selects an issue while
it is genuinely open, other work closes it on GitHub before our branch-cut,
and the stale local cache keeps the build going to a duplicate PR. This
drives the REAL ``ImplementPhase.run_batch`` against the wired
``FakeGitHub``/``FakeWorkspace`` — the same fakes a second factory actor
would see — and closes the issue between pick and branch-cut.

Integration-level: the abandon decision is made by the real
``issue-state`` gate reading the real ``FakeGitHub.get_issue_state`` (wired
onto the harness PR port), the worktree would be created by the real
``FakeWorkspace``, and the PR by the real FakeGitHub PR path. Nothing is
hand-labelled; the only scripted step is the out-of-band close, which is the
incident being reproduced.
"""

from __future__ import annotations

import pytest

from tests.conftest import TaskFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario

_ISSUE = 5157
_READY = "hydraflow-ready"


@pytest.mark.asyncio
async def test_issue_closed_between_pick_and_branch_cut_abandons_build(
    tmp_path,
) -> None:
    """No agent build, no worktree, no PR — the slot returns terminal."""
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "Do the thing", "body", labels=[_READY])

    # Grab the workspace handle up front (also pins the public `workspace`
    # accessor this scenario relies on): `created` records every worktree the
    # real implement phase cuts.
    workspace = world.workspace

    # The pick happened while the issue was open; the Task now sits in the
    # ready queue. Then other work merges a fix and closes the issue on
    # GitHub — the selection→branch-cut window of #11457.
    world.harness.seed_issue(
        TaskFactory.create(id=_ISSUE, title="Do the thing", body="body", tags=[_READY]),
        stage="ready",
    )
    await world.github.close_issue(_ISSUE)
    assert await world.github.get_issue_state(_ISSUE) == "COMPLETED"

    results, _ = await world.harness.implement_phase.run_batch()

    # The build was abandoned before the branch was cut: no worktree, no PR.
    assert workspace.created == [], "a resolved issue must not cut a worktree"
    assert world.github.pr_for_issue(_ISSUE) is None, (
        "a resolved issue must not open a duplicate PR"
    )
    wr = next(w for w in results if w.issue_number == _ISSUE)
    assert wr.success is False
    assert "resolved" in (wr.error or "").lower()

    # Terminal 'completed' status — not 'failed', so no retry sweeper or HITL
    # route may pick the resolved issue back up.
    state = world.harness.implement_phase._state.to_dict()
    assert state["processed_issues"].get(str(_ISSUE)) == "completed"
    assert world.harness.implement_phase._state.get_hitl_cause(_ISSUE) is None
    assert "hydraflow-diagnose" not in world.github.issue(_ISSUE).labels

    # The slot returned: the resolved issue is not re-queued for another pick.
    assert world.harness.store.get_implementable(10) == []


@pytest.mark.asyncio
async def test_issue_still_open_builds_normally(tmp_path) -> None:
    """Control: with the issue open at branch-cut, the same wiring builds.

    Guards against the gate over-firing through the FakeGitHub wiring — the
    scenario-tier parity check for the fail-open contract.
    """
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "Do the other thing", "body", labels=[_READY])
    workspace = world.workspace

    world.harness.seed_issue(
        TaskFactory.create(
            id=_ISSUE, title="Do the other thing", body="body", tags=[_READY]
        ),
        stage="ready",
    )

    results, _ = await world.harness.implement_phase.run_batch()

    wr = next(w for w in results if w.issue_number == _ISSUE)
    assert wr.success is True, "an open issue must still build through the fakes"
    assert _ISSUE in workspace.created
