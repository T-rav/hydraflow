"""MockWorld scenario — durable ``hydraflow-in-progress`` build claim (#10168).

Two factory actors share one GitHub (the MockWorld ``FakeGitHub``). Actor A
starts a build on a ready issue; the REAL ``ImplementPhase`` stamps
``hydraflow-in-progress`` on the shared GitHub. A SECOND actor — a fresh
``IssueStore``, standing in for an out-of-band Agent dispatch or a parallel
operator session — then re-reads GitHub and must SKIP the claimed issue. That
is the cross-actor double-pick collision (#10141) the in-memory
``_eagerly_transitioned`` fast-path cannot prevent, because the second actor's
in-process state is empty for that issue. When the build ends and the claim is
released, the issue becomes pickable again.

Integration-level: the claim is applied/cleared by REAL ``ImplementPhase``
methods against the wired ``FakeGitHub``, and the skip decision is made by the
REAL ``IssueStore._is_eligible`` in an independent store. Nothing is
hand-labelled.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import IssueStore
from models import Task
from tests.helpers import ConfigFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario

_ISSUE = 4242
_READY = "hydraflow-ready"
_CLAIM = "hydraflow-in-progress"


def _second_actor_store() -> IssueStore:
    """A fresh IssueStore modelling a second factory instance / out-of-band
    dispatch. Its ``ready_label`` matches the seeded issue so the issue routes
    to the READY queue; eligibility is then the only thing that can gate it."""
    config = ConfigFactory.create(ready_label=[_READY])
    return IssueStore(config, AsyncMock(), EventBus())


def _read_from_github(world: MockWorld, number: int) -> Task:
    """Build a Task from the issue's CURRENT GitHub labels — what any actor
    polling GitHub afresh would see."""
    labels = list(world.github.issue(number).labels)
    return Task(id=number, title=f"Issue {number}", body="body", tags=labels)


@pytest.mark.asyncio
async def test_claimed_ready_issue_is_skipped_by_a_second_actor(tmp_path) -> None:
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "Add claim label", "body", labels=[_READY])

    impl = world.harness.implement_phase

    # First pick / build start: Actor A stamps the durable claim (real code).
    await impl._claim_issue(_ISSUE)

    gh_labels = world.github.issue(_ISSUE).labels
    assert _CLAIM in gh_labels, "build start must stamp the durable claim on GitHub"
    assert _READY in gh_labels, "claim is additive — the ready label still stands"

    # Second pick: a different actor polls GitHub and routes the issue. It is
    # ready-labelled, so it lands in the READY queue — but the durable claim
    # makes it ineligible, so the second actor skips it.
    actor_b = _second_actor_store()
    actor_b._route_issues([_read_from_github(world, _ISSUE)])
    assert actor_b.get_implementable(10) == [], (
        "a second actor must skip an issue already claimed on GitHub (#10141)"
    )

    # Build ends: Actor A releases the claim (real code). The issue is now a
    # plain ready issue again, and the already-running actor refreshes it.
    await impl._release_claim(_ISSUE)
    assert _CLAIM not in world.github.issue(_ISSUE).labels

    actor_b._route_issues([_read_from_github(world, _ISSUE)])
    assert [t.id for t in actor_b.get_implementable(10)] == [_ISSUE], (
        "once the claim is cleared the issue must be re-pickable — never stuck"
    )


@pytest.mark.asyncio
async def test_pr_open_swap_clears_the_claim(tmp_path) -> None:
    # The ready→review transition at PR-open must drop the claim, because
    # in_progress_label is a member of all_pipeline_labels (like human-required).
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "Add claim label", "body", labels=[_READY])
    impl = world.harness.implement_phase

    await impl._claim_issue(_ISSUE)
    assert _CLAIM in world.github.issue(_ISSUE).labels

    # PRManager.transition("review") → swap_pipeline_labels (wired to FakeGitHub,
    # which strips every hydraflow-* label and applies the new one).
    await world.harness.prs.transition(_ISSUE, "review")

    labels = world.github.issue(_ISSUE).labels
    assert _CLAIM not in labels, "ready→review swap must clear the build claim"
    assert "hydraflow-review" in labels
