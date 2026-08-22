"""MockWorld scenario — implement-seam attempt waste (#11568).

Drives the REAL ``ImplementPhase.run_batch`` against the wired ``FakeGitHub``
/ ``FakeWorkspace`` / real ``IssueStore`` / real ``IssueCache`` with the
scripted ``FakeLLM`` agent runner at the spawn seam, and pins the two seams
the throughput regression named:

1. **Tiered timeout.** A triage complexity-1 issue's implement spawn receives
   half of ``agent_timeout``; a complexity-5 issue receives the ceiling; an
   unclassified issue receives the ceiling.
2. **Zero-commit first attempt routes to diagnose.** One zero-commit result
   moves the issue to ``hydraflow-diagnose`` with the transcript tail in the
   escalation context, and a second ``run_batch`` spawns NOTHING — counted at
   the fake runner. A credit-exhausted first attempt, by contrast, raises
   straight through (the ADR-0119 pause path) and leaves the issue at ready.
"""

from __future__ import annotations

import pytest

from subprocess_util import CreditExhaustedError
from tests.conftest import TaskFactory, WorkerResultFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario_loops

_READY = "hydraflow-ready"
_DIAGNOSE = "hydraflow-diagnose"
_TIER_ONE = 7101
_TIER_FIVE = 7105
_UNSCORED = 7100
_ZERO = 7201
_CAPPED = 7202
_TRANSCRIPT = "agent reasoning " * 400 + "FINAL-LINE"


def _seed_ready(world: MockWorld, number: int, title: str) -> None:
    world.add_issue(number, title, "body", labels=[_READY])
    world.harness.seed_issue(
        TaskFactory.create(id=number, title=title, body="body", tags=[_READY]),
        stage="ready",
    )


def _classify(world: MockWorld, number: int, complexity: int) -> None:
    world.harness.issue_cache.record_classification(
        number,
        issue_type="feature",
        complexity_score=complexity,
        complexity_rank="low" if complexity < 5 else "medium",
        routing_outcome="plan",
    )


def _zero_commit(number: int) -> object:
    return WorkerResultFactory.create(
        issue_number=number,
        branch=f"agent/issue-{number}",
        success=False,
        error="No commits found on branch",
        commits=0,
        transcript=_TRANSCRIPT,
    )


# ---------------------------------------------------------------------------
# Seam 1 — tiered implement timeout
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_tier_one_spawn_gets_half_the_ceiling_and_tier_five_the_ceiling(
    tmp_path,
) -> None:
    world = MockWorld(tmp_path)
    ceiling = world.harness.config.agent_timeout
    _seed_ready(world, _TIER_ONE, "Tiny fix")
    _seed_ready(world, _TIER_FIVE, "Big feature")
    _classify(world, _TIER_ONE, complexity=1)
    _classify(world, _TIER_FIVE, complexity=5)

    await world.harness.implement_phase.run_batch()

    agents = world._llm.agents
    assert agents.timeouts_seen_for(_TIER_ONE) == [ceiling // 2]
    assert agents.timeouts_seen_for(_TIER_FIVE) == [ceiling]


@pytest.mark.asyncio
async def test_unclassified_issue_spawns_with_the_ceiling(tmp_path) -> None:
    """No triage record → no evidence to shrink the budget → the ceiling."""
    world = MockWorld(tmp_path)
    _seed_ready(world, _UNSCORED, "Never triaged")

    await world.harness.implement_phase.run_batch()

    assert world._llm.agents.timeouts_seen_for(_UNSCORED) == [
        world.harness.config.agent_timeout
    ]


# ---------------------------------------------------------------------------
# Seam 2 — zero-commit first attempt → diagnose, no second spawn
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_zero_commit_first_attempt_routes_to_diagnose(tmp_path) -> None:
    world = MockWorld(tmp_path)
    _seed_ready(world, _ZERO, "Produces nothing")
    world._llm.script_implement(_ZERO, [_zero_commit(_ZERO)])

    await world.harness.implement_phase.run_batch()

    assert _DIAGNOSE in world.github.issue(_ZERO).labels
    assert _READY not in world.github.issue(_ZERO).labels


@pytest.mark.asyncio
async def test_zero_commit_escalation_carries_the_transcript_tail(tmp_path) -> None:
    world = MockWorld(tmp_path)
    _seed_ready(world, _ZERO, "Produces nothing")
    world._llm.script_implement(_ZERO, [_zero_commit(_ZERO)])

    await world.harness.implement_phase.run_batch()

    context = world.harness.state.get_escalation_context(_ZERO)
    assert context is not None
    assert context.origin_phase == "implement"
    assert (context.agent_transcript or "").endswith("FINAL-LINE")


@pytest.mark.asyncio
async def test_no_second_implement_attempt_is_spawned(tmp_path) -> None:
    """Two ticks, one spawn: the routed issue has left the ready queue."""
    world = MockWorld(tmp_path)
    _seed_ready(world, _ZERO, "Produces nothing")
    world._llm.script_implement(
        _ZERO,
        [
            _zero_commit(_ZERO),
            WorkerResultFactory.create(issue_number=_ZERO, success=True, commits=1),
        ],
    )

    await world.harness.implement_phase.run_batch()
    await world.harness.implement_phase.run_batch()

    assert len(world._llm.agents.run_calls_for(_ZERO)) == 1
    assert world.harness.state.get_issue_attempts(_ZERO) == 1
    assert world.github.pr_for_issue(_ZERO) is None


@pytest.mark.asyncio
async def test_credit_exhausted_first_attempt_raises_and_stays_ready(
    tmp_path,
) -> None:
    """ADR-0119: a credit cap propagates for the orchestrator's pause — it is
    never mistaken for a zero-commit failure and never routes to diagnose."""
    world = MockWorld(tmp_path)
    _seed_ready(world, _CAPPED, "Hits the cap")
    world._llm.script_implement(_CAPPED, [CreditExhaustedError("limit reached")])

    with pytest.raises(CreditExhaustedError):
        await world.harness.implement_phase.run_batch()

    assert _READY in world.github.issue(_CAPPED).labels
    assert _DIAGNOSE not in world.github.issue(_CAPPED).labels
    assert world.harness.state.get_hitl_cause(_CAPPED) is None
    assert len(world._llm.agents.run_calls_for(_CAPPED)) == 1
