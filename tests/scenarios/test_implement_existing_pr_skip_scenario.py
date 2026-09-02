"""MockWorld scenario — implement skips an issue a PR already closes (#11981).

Drives the REAL ``ImplementPhase.run_batch`` against the wired ``FakeGitHub``,
with an open PR staged on a CONVENTIONAL branch whose body declares
``Closes #N``. That is the shape the pre-implementation check could not see: it
predicted ``agent/issue-{N}`` and matched by literal branch-name equality, so a
complete PR under ``fix/{N}-slug`` was invisible and the agent re-implemented
work that already existed.

Unit tests see the lookup and the branch it guards. Only this layer sees the
thing that actually costs money: whether an agent SPAWNS for an issue somebody
has already finished.

The harness wires `implement_phase._prs` to a mock rather than to
`world.github`, so the two reads are configured on it here. That is the
harness's shape, not a choice — what this still proves, and what unit tests
cannot, is the WIRING: real `run_batch`, real `_flow_decompose`, real transition
to review, and no spawn at the agent seam.
"""

from __future__ import annotations

import pytest

from tests.conftest import TaskFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario_loops

_READY = "hydraflow-ready"
_ISSUE = 7711
_PR = 4242


def _seed_ready(world: MockWorld, number: int) -> None:
    world.add_issue(number, "already done", "body", labels=[_READY])
    world.harness.seed_issue(
        TaskFactory.create(id=number, title="already done", body="body", tags=[_READY]),
        stage="ready",
    )


def _stage_pr(world: MockWorld, *, body: str) -> None:
    """An open PR on a branch the name check cannot predict."""
    from models import PRListItem  # noqa: PLC0415

    prs = world.harness.implement_phase._prs
    prs.list_all_open_prs.return_value = [
        PRListItem(
            pr=_PR,
            issue=0,  # derived from the branch name upstream — the blind spot
            branch=f"fix/{_ISSUE}-done-by-hand",
            title="fix(thing): done by hand",
        )
    ]
    prs.get_pr_title_and_body.return_value = ("fix(thing): done by hand", body)


@pytest.mark.asyncio
async def test_no_agent_spawns_when_an_open_pr_declares_the_issue(tmp_path) -> None:
    world = MockWorld(tmp_path)
    _seed_ready(world, _ISSUE)
    _stage_pr(world, body=f"Closes #{_ISSUE}")

    await world.harness.implement_phase.run_batch()

    assert world._llm.agents.run_calls_for(_ISSUE) == []


@pytest.mark.asyncio
async def test_the_agent_still_runs_when_nothing_declares_the_issue(
    tmp_path,
) -> None:
    """The decoy, and the one that matters.

    A check that skipped implementation whenever ANY open PR existed would
    satisfy the test above while stopping the factory from building anything.
    A bare mention is not a promise to close.
    """
    world = MockWorld(tmp_path)
    _seed_ready(world, _ISSUE)
    _stage_pr(world, body=f"related to #{_ISSUE}, but closes nothing")

    await world.harness.implement_phase.run_batch()

    assert world._llm.agents.run_calls_for(_ISSUE) != []
