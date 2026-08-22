"""MockWorld scenario — READY counters follow the implement lifecycle (#11551).

The REAL ``ImplementPhase.run_batch`` drains the ready queue and wraps the
build in ``store_lifecycle(store, n, "implement")`` — the dashboard-facing
phase name. The REAL ``IssueStore`` keys ``active_count`` and
``total_processed`` on ``IssueStoreStage.READY`` (``"ready"``). Before
#11551 the two vocabularies never met: an implementer was running, the
agent was being invoked, and ``/api/queue`` said ``active_count.ready == 0``
and — once the build finished — ``total_processed.ready == 0``.

The only seam touched is the agent runner the world already wires
(``FakeLLM.agents.run``): it is wrapped so the queue stats can be read at
the exact moment the agent is running. Nothing is hand-marked active.
"""

from __future__ import annotations

from typing import Any

import pytest

from models import QueueStats
from tests.conftest import TaskFactory
from tests.scenarios.fakes import MockWorld

pytestmark = pytest.mark.scenario_loops

_ISSUE = 11551
_READY = "hydraflow-ready"


@pytest.mark.asyncio
async def test_running_implementer_counts_as_ready_then_processed(tmp_path) -> None:
    world = MockWorld(tmp_path)
    world.add_issue(_ISSUE, "Build the thing", "body", labels=[_READY])
    h = world.harness
    h.seed_issue(
        TaskFactory.create(
            id=_ISSUE, title="Build the thing", body="body", tags=[_READY]
        ),
        stage="ready",
    )

    # Observe the store at the moment the agent runs — i.e. inside the real
    # store_lifecycle("implement") window — without touching the phase.
    while_running: list[QueueStats] = []
    fake_run = h.agents.run

    async def observed_run(*args: Any, **kwargs: Any) -> Any:
        while_running.append(h.store.get_queue_stats().model_copy(deep=True))
        return await fake_run(*args, **kwargs)

    h.agents.run = observed_run

    before = h.store.get_queue_stats()
    assert before.queue_depth["ready"] == 1
    assert before.active_count["ready"] == 0
    assert before.total_processed["ready"] == 0

    results, _ = await h.implement_phase.run_batch()

    wr = next(w for w in results if w.issue_number == _ISSUE)
    assert wr.success is True, wr.error
    assert len(while_running) == 1, "the agent must have run exactly once"
    assert while_running[0].active_count["ready"] == 1, (
        "a running implementer must show under active_count.ready (#11551)"
    )
    assert while_running[0].total_processed["ready"] == 0

    after = h.store.get_queue_stats()
    assert after.active_count["ready"] == 0
    assert after.total_processed["ready"] == 1, (
        "a finished build must bump total_processed.ready (#11551)"
    )
    # Other stage counters are untouched by the implement lifecycle.
    assert {k: v for k, v in after.total_processed.items() if k != "ready"} == {
        "find": 0,
        "plan": 0,
        "review": 0,
        "hitl": 0,
    }
