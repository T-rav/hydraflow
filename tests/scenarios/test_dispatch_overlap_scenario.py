"""Runner-level scenario for the dispatch-overlap guard (#10778).

Drives the REAL ``ImplementPhase.run_batch`` slot-filling pool against a small
fake ``IssueStore`` that models the ready queue, with the heavy per-issue flow
(``_worker_inner``) replaced by a concurrency recorder. This exercises the real
``_supply_live`` reserve/hold path and the real ``_worker`` release, proving:

* two units whose predicted scopes overlap are SERIALIZED (never build at once),
  while still both eventually building — the held one is re-dispatched, not
  dropped; and
* two non-overlapping units still build CONCURRENTLY (no false-positive
  serialization / throughput regression); and
* the ``dispatch_overlap_guard_enabled`` kill-switch restores concurrent
  dispatch for overlapping units when off.

Pattern B (direct instantiation): the runner's reaction surface is what matters,
so collaborators are scripted rather than run through a full MockWorld.
"""

from __future__ import annotations

import asyncio
from collections import deque

import pytest

from models import Task, WorkerResult
from tests.helpers import ConfigFactory, make_implement_phase

pytestmark = pytest.mark.scenario_loops


class _FakeReadyStore:
    """Minimal IssueStore stand-in modelling only the ready queue.

    Faithful to the two behaviours ``run_batch`` depends on: ``get_implementable``
    dequeues (and claims) one ready task; ``enqueue_transition(task, "ready")``
    puts a held task back so a later refill round re-dispatches it.
    """

    def __init__(self, tasks: list[Task]) -> None:
        self._ready: deque[Task] = deque(tasks)
        self._in_flight: set[int] = set()
        self.completed: list[int] = []

    def get_implementable(self, max_count: int) -> list[Task]:
        out: list[Task] = []
        while self._ready and len(out) < max_count:
            task = self._ready.popleft()
            self._in_flight.add(task.id)
            out.append(task)
        return out

    def release_in_flight(self, issue_numbers: set[int]) -> None:
        self._in_flight -= set(issue_numbers)

    def enqueue_transition(self, task: Task, next_stage: str) -> None:
        self._in_flight.discard(task.id)
        if all(t.id != task.id for t in self._ready):
            self._ready.append(task)

    def mark_active(self, issue_number: int, stage: str) -> None:
        return None

    def mark_complete(self, issue_number: int) -> None:
        self._in_flight.discard(issue_number)
        self.completed.append(issue_number)


class _ConcurrencyRecorder:
    """Records peak concurrent worker count and dispatch order."""

    def __init__(self) -> None:
        self._live = 0
        self.max_live = 0
        self.order: list[int] = []

    async def run(self, idx: int, issue: Task, branch: str) -> WorkerResult:
        self._live += 1
        self.max_live = max(self.max_live, self._live)
        self.order.append(issue.id)
        try:
            await asyncio.sleep(0.02)
        finally:
            self._live -= 1
        return WorkerResult(issue_number=issue.id, branch=branch, success=True)


def _build_phase(tasks: list[Task], *, guard_enabled: bool = True):
    config = ConfigFactory.create(max_workers=2)
    config = config.model_copy(update={"dispatch_overlap_guard_enabled": guard_enabled})
    phase, _wt, _prs = make_implement_phase(config, [])
    phase._store = _FakeReadyStore(tasks)
    recorder = _ConcurrencyRecorder()
    phase._worker_inner = recorder.run
    return phase, recorder


class TestDispatchOverlapScenario:
    async def test_overlapping_units_are_serialized(self) -> None:
        tasks = [
            Task(id=10772, title="lesson survival", body="touches #10754"),
            Task(id=10773, title="wiki citations", body="also touches #10754"),
        ]
        phase, recorder = _build_phase(tasks)
        await phase.run_batch()
        assert recorder.max_live == 1

    async def test_serialized_unit_is_not_dropped(self) -> None:
        tasks = [
            Task(id=10772, title="lesson survival", body="touches #10754"),
            Task(id=10773, title="wiki citations", body="also touches #10754"),
        ]
        phase, recorder = _build_phase(tasks)
        await phase.run_batch()
        assert set(recorder.order) == {10772, 10773}

    async def test_non_overlapping_units_dispatch_concurrently(self) -> None:
        tasks = [
            Task(id=1, title="alpha", body="edit src/alpha.py, relates to #900"),
            Task(id=2, title="beta", body="edit src/beta.py, relates to #901"),
        ]
        phase, recorder = _build_phase(tasks)
        await phase.run_batch()
        assert recorder.max_live == 2

    async def test_kill_switch_off_lets_overlapping_units_run_concurrently(
        self,
    ) -> None:
        tasks = [
            Task(id=10772, title="lesson survival", body="touches #10754"),
            Task(id=10773, title="wiki citations", body="also touches #10754"),
        ]
        phase, recorder = _build_phase(tasks, guard_enabled=False)
        await phase.run_batch()
        assert recorder.max_live == 2
