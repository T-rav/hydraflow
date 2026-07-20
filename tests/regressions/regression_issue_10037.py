"""Regression pins for issue #10037 — selectable work-queue discipline.

Two invariants that a future change to ``IssueStore._take_from_queue`` could
silently break:

1. **``fifo`` is a behaviour pin.** ``fifo`` is the escape hatch back to the
   pre-#10037 oldest-first ordering (the default is now ``weighted_mix``). Its
   whole value is being a *faithful* arrival-order pass-through: an operator
   setting ``fifo`` must get exactly the pre-#10037 behaviour with no
   reordering. If that ever drifts, the escape hatch silently stops being one.

2. **The crate (milestone) gate was absorbed, not retired, and unmilestoned
   repos keep flowing.** #10037 folded the dormant crate scope-filter
   (`issue_store.py`, ``CrateManager.is_in_active_crate``) into the strategy's
   eligibility check rather than deleting it, because the dashboard crate UI and
   the orchestrator lifecycle still consume ``CrateManager``. The load-bearing
   property is that with **no active crate** — the real repo state, zero
   milestones — every task flows regardless of strategy. The known hazard the
   issue flagged (activating a crate wedges an unmilestoned backlog, because
   ``is_in_active_crate`` returns ``False`` for unmilestoned tasks) is preserved
   deliberately and pinned here so retirement is a conscious future decision,
   not an accident.
"""

from __future__ import annotations

import random
import sys
from collections.abc import Callable
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from models import Task
from queue_strategy import BandWeights, QueueStrategy, order_queue
from tests.helpers import ConfigFactory


class _FakeCrateManager:
    """Minimal stand-in exposing the two members the take path consults."""

    def __init__(
        self,
        active_crate_number: int | None,
        is_in_active_crate: Callable[[Task], bool],
    ) -> None:
        self._active = active_crate_number
        self._predicate = is_in_active_crate

    @property
    def active_crate_number(self) -> int | None:
        return self._active

    def is_in_active_crate(self, task: Task) -> bool:
        return self._predicate(task)


def _store(strategy: QueueStrategy) -> IssueStore:
    config = ConfigFactory.create()
    config.queue_strategy = strategy
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    store = IssueStore(config, fetcher, EventBus())
    store._queue_rng = random.Random(0)
    return store


def _enqueue(store: IssueStore, *tasks: Task) -> None:
    for task in tasks:
        store._queues[STAGE_READY].append(task)
        store._queue_members[STAGE_READY].add(task.id)


def test_fifo_reproduces_pre_10037_oldest_first_order_exactly() -> None:
    store = _store(QueueStrategy.FIFO)
    _enqueue(
        store,
        Task(id=1, title="oldest P2", tags=["P2"]),
        Task(id=2, title="a P0 filed later", tags=["P0"]),
        Task(id=3, title="a P1 filed later", tags=["P1"]),
        Task(id=4, title="newest unlabelled", tags=[]),
    )

    # Arrival order, untouched — the deque order, not the priority order.
    assert [t.id for t in store.get_implementable(4)] == [1, 2, 3, 4]


def test_unmilestoned_repo_keeps_flowing_when_no_crate_is_active() -> None:
    # Zero milestones ⇒ active_crate_number is None ⇒ is_in_active_crate is
    # never consulted, so an unmilestoned task dispatches under every strategy.
    unmilestoned = Task(id=42, title="unmilestoned work", tags=["P1"])
    for strategy in QueueStrategy:
        store = _store(strategy)
        store.set_crate_manager(
            _FakeCrateManager(
                active_crate_number=None, is_in_active_crate=lambda _t: False
            )
        )
        _enqueue(store, unmilestoned)

        assert [t.id for t in store.get_implementable(1)] == [42], strategy


def test_activating_a_crate_still_gates_out_unmilestoned_work() -> None:
    # The absorbed gate is preserved: with a crate active, a task the crate
    # manager rejects is held back (the pre-existing wedge hazard the issue
    # flagged). Pinned so retiring the gate is a deliberate future choice.
    store = _store(QueueStrategy.WEIGHTED_MIX)
    store.set_crate_manager(
        _FakeCrateManager(active_crate_number=7, is_in_active_crate=lambda _t: False)
    )
    _enqueue(store, Task(id=1, title="unmilestoned P0", tags=["P0"]))

    assert store.get_implementable(1) == []


def test_an_unhandled_queue_strategy_raises_rather_than_silently_mixing() -> None:
    # ``order_queue`` originally ended with a bare ``return _weighted_mix(...)``,
    # so anything that was not ``fifo`` or ``priority`` was dispatched as
    # ``weighted_mix``. Nothing invalid reaches it today — HydraFlowConfig
    # validates the field and PATCH /api/control/config re-validates through
    # model_validate and 422s — but a NEW member added to QueueStrategy without
    # a matching branch would have been silently mis-dispatched.
    #
    # That is the dangerous shape for a scheduler: it keeps draining the queue
    # and picking work, just under the wrong discipline, with no error, no log
    # line, and every existing test still green.
    with pytest.raises(ValueError, match="unhandled queue strategy"):
        order_queue(
            [Task(id=1, title="issue 1")],
            "not_a_strategy",  # type: ignore[arg-type]
            BandWeights(p1=3, p2=2, unprioritised=1),
        )


def test_every_declared_queue_strategy_still_dispatches() -> None:
    # The converse of the guard: it must not have made a real discipline
    # unreachable. Every enum member still returns the full task set.
    tasks = [Task(id=1, title="a", tags=["P1"]), Task(id=2, title="b")]
    weights = BandWeights(p1=3, p2=2, unprioritised=1)

    for strategy in QueueStrategy:
        ordered = order_queue(tasks, strategy, weights, rng=random.Random(0))

        assert sorted(t.id for t in ordered) == [1, 2], strategy
