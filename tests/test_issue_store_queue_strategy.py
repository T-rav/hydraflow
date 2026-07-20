"""IssueStore honours the configured work-queue strategy (#10037).

``tests/test_queue_strategy.py`` proves the ordering engine in isolation. These
tests prove the *wiring*: that the store actually consults the strategy when
dispatching, that the knob is re-read live, and that eligibility rules still
win over priority.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

import pytest

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from models import Task
from queue_strategy import QueueStrategy
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _make_store(strategy: QueueStrategy = QueueStrategy.WEIGHTED_MIX) -> IssueStore:
    config = ConfigFactory.create()
    config.queue_strategy = strategy
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    return IssueStore(config, fetcher, EventBus())


def _queue(store: IssueStore, *tasks: Task) -> None:
    for task in tasks:
        store._queues[STAGE_READY].append(task)
        store._queue_members[STAGE_READY].add(task.id)


def _ready(id: int, priority: str | None = None) -> Task:
    tags = ["hydraflow-ready"] + ([priority] if priority else [])
    return TaskFactory.create(id=id, tags=tags)


def test_a_fresh_p1_is_dispatched_ahead_of_an_older_unlabelled_issue() -> None:
    # The headline #10037 acceptance criterion. Pre-#10037 the oldest issue won
    # unconditionally, so a P1 filed today queued behind the whole backlog.
    store = _make_store()
    _queue(
        store,
        _ready(id=1),
        _ready(id=2),
        _ready(id=3, priority="P1"),
    )

    assert [t.id for t in store.get_implementable(1)] == [3]


def test_p0_preempts_every_other_band() -> None:
    store = _make_store()
    _queue(
        store,
        _ready(id=1, priority="P1"),
        _ready(id=2, priority="P2"),
        _ready(id=3, priority="P0"),
    )

    assert [t.id for t in store.get_implementable(1)] == [3]


def test_fifo_strategy_reproduces_the_pre_10037_oldest_first_behaviour() -> None:
    store = _make_store(QueueStrategy.FIFO)
    _queue(
        store,
        _ready(id=1),
        _ready(id=2, priority="P0"),
        _ready(id=3, priority="P1"),
    )

    assert [t.id for t in store.get_implementable(3)] == [1, 2, 3]


def test_the_strategy_knob_is_re_read_on_every_dequeue() -> None:
    # ``live=True`` in the settings registry is a promise to the operator that
    # flipping this in the dashboard takes effect on the next tick. If the
    # store ever caches the strategy at construction, this fails.
    store = _make_store(QueueStrategy.FIFO)
    _queue(store, _ready(id=1), _ready(id=2, priority="P0"))

    assert [t.id for t in store.get_implementable(1)] == [1]

    store._config.queue_strategy = QueueStrategy.WEIGHTED_MIX

    assert [t.id for t in store.get_implementable(1)] == [2]


def test_priority_does_not_override_the_human_required_guard() -> None:
    # Eligibility is a correctness rule (ADR-0084 pillar C); ordering must not
    # be able to promote an escalated issue back into the pipeline.
    store = _make_store()
    escalated = TaskFactory.create(
        id=1, tags=["hydraflow-ready", "P0", "human-required"]
    )
    _queue(store, escalated, _ready(id=2, priority="P2"))

    assert [t.id for t in store.get_implementable(1)] == [2]


def test_an_active_issue_is_skipped_even_when_it_outranks_the_rest() -> None:
    store = _make_store()
    _queue(store, _ready(id=1, priority="P0"), _ready(id=2, priority="P2"))
    store.mark_active(1, STAGE_READY)

    assert [t.id for t in store.get_implementable(1)] == [2]


def test_taking_work_leaves_the_rest_queued_in_arrival_order() -> None:
    # Ordering is a read-time concern; permuting the stored deque would leak
    # into queue snapshots and stats for no benefit.
    store = _make_store()
    _queue(
        store,
        _ready(id=1),
        _ready(id=2, priority="P2"),
        _ready(id=3, priority="P0"),
    )

    store.get_implementable(1)

    assert [t.id for t in store._queues[STAGE_READY]] == [1, 2]
    assert store._queue_members[STAGE_READY] == {1, 2}


def test_lower_bands_still_advance_under_a_flood_of_higher_priority_work() -> None:
    # The starvation guarantee, asserted through the real store rather than the
    # engine: with weights P1=3/P2=2/none=1 a P2 must appear within one cycle.
    store = _make_store()
    _queue(store, *[_ready(id=100 + i, priority="P2") for i in range(3)])
    _queue(store, *[_ready(id=i, priority="P1") for i in range(30)])

    dispatched = [t.id for t in store.get_implementable(6)]

    assert any(number >= 100 for number in dispatched)


@pytest.mark.parametrize("strategy", list(QueueStrategy))
def test_no_queued_task_is_lost_or_duplicated_by_any_strategy(
    strategy: QueueStrategy,
) -> None:
    store = _make_store(strategy)
    _queue(
        store,
        _ready(id=1, priority="P2"),
        _ready(id=2),
        _ready(id=3, priority="P0"),
        _ready(id=4, priority="P1"),
    )

    taken = [t.id for t in store.get_implementable(2)]
    left = [t.id for t in store._queues[STAGE_READY]]

    assert sorted(taken + left) == [1, 2, 3, 4]
