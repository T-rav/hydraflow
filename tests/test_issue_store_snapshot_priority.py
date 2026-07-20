"""Snapshot entries carry priority + dispatch rank so the UI can visualise the
work-queue strategy (#10067).

The board is arrival-ordered today and carries no priority, so with
``weighted_mix`` as the default a user cannot see which issue the factory will
pick next. These pins enrich each *queued* snapshot entry with:

* ``priority`` — the P0/P1/P2 band (``queue_strategy.band_of``), so cards can
  show it; and
* ``dispatch_rank`` — the position ``order_queue`` would pick it in, so the UI
  can render a stage in dispatch order without reimplementing the algorithm.

The emitted list stays in arrival order (rank is a field, not a re-sort), so
every existing snapshot consumer is unaffected — only clients that opt into
sorting by ``dispatch_rank`` see dispatch order.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from queue_strategy import QueueStrategy
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _make_store(strategy: QueueStrategy = QueueStrategy.WEIGHTED_MIX) -> IssueStore:
    config = ConfigFactory.create()
    config.queue_strategy = strategy
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    return IssueStore(config, fetcher, EventBus())


def _ready(store: IssueStore, id: int, priority: str | None = None) -> None:
    # Enqueue straight into the READY deque (ConfigFactory's ready_label is
    # 'test-label', so routing a 'hydraflow-ready' tag would land nowhere).
    tags = ["hydraflow-ready"] + ([priority] if priority else [])
    task = TaskFactory.create(id=id, tags=tags)
    store._queues[STAGE_READY].append(task)
    store._queue_members[STAGE_READY].add(task.id)


def test_queued_entries_carry_their_priority_band() -> None:
    store = _make_store()
    _ready(store, 1, "P1")
    _ready(store, 2)
    _ready(store, 3, "P0")

    by_number = {
        e["issue_number"]: e for e in store.get_pipeline_snapshot()[STAGE_READY]
    }

    assert by_number[1]["priority"] == "P1"
    assert by_number[2]["priority"] == "none"
    assert by_number[3]["priority"] == "P0"


def test_dispatch_rank_reflects_the_active_strategy_not_arrival_order() -> None:
    # With weighted_mix, the P0 is picked first, so it gets rank 0 even though
    # it arrived last. This is the whole point: the rank encodes what the
    # factory will actually do, which arrival order does not.
    store = _make_store(QueueStrategy.WEIGHTED_MIX)
    _ready(store, 1, "P2")
    _ready(store, 2)
    _ready(store, 3, "P0")

    entries = store.get_pipeline_snapshot()[STAGE_READY]
    rank_of = {e["issue_number"]: e["dispatch_rank"] for e in entries}

    assert rank_of[3] == 0  # the P0 is dispatched first


def test_queued_entries_stay_in_arrival_order_on_the_wire() -> None:
    # Rank is a field, not a re-sort: the list itself keeps arrival order so
    # existing snapshot consumers (and their tests) are unaffected. The new UI
    # opts into dispatch order by sorting on dispatch_rank.
    store = _make_store(QueueStrategy.WEIGHTED_MIX)
    _ready(store, 1, "P2")
    _ready(store, 2, "P0")
    _ready(store, 3, "P1")

    order = [e["issue_number"] for e in store.get_pipeline_snapshot()[STAGE_READY]]

    assert order == [1, 2, 3]


def test_dispatch_ranks_are_a_contiguous_permutation_within_a_stage() -> None:
    # Sorting the stage by dispatch_rank must reproduce order_queue's output
    # exactly — no gaps, no ties, every queued entry ranked.
    store = _make_store(QueueStrategy.PRIORITY)
    _ready(store, 1, "P2")
    _ready(store, 2)
    _ready(store, 3, "P0")
    _ready(store, 4, "P1")

    entries = store.get_pipeline_snapshot()[STAGE_READY]
    ranks = sorted(e["dispatch_rank"] for e in entries)

    assert ranks == [0, 1, 2, 3]
    dispatch_order = [
        e["issue_number"] for e in sorted(entries, key=lambda e: e["dispatch_rank"])
    ]
    assert dispatch_order == [3, 4, 1, 2]  # P0, P1, P2, none — strict priority


def test_fifo_strategy_ranks_match_arrival_order() -> None:
    store = _make_store(QueueStrategy.FIFO)
    _ready(store, 10)
    _ready(store, 11, "P0")
    _ready(store, 12, "P1")

    entries = store.get_pipeline_snapshot()[STAGE_READY]
    dispatch_order = [
        e["issue_number"] for e in sorted(entries, key=lambda e: e["dispatch_rank"])
    ]

    assert dispatch_order == [10, 11, 12]  # fifo == arrival, priority ignored


def test_active_entries_have_no_dispatch_rank() -> None:
    # Rank is a "what's next in the queue" concept; an active issue is already
    # being worked, so it carries priority for display but no rank.
    store = _make_store()
    store._route_issues([TaskFactory.create(id=5, tags=["hydraflow-ready", "P1"])])
    store.get_implementable(1)
    store.mark_active(5, STAGE_READY)

    entry = store.get_pipeline_snapshot()[STAGE_READY][0]

    assert entry["status"] == "active"
    assert "dispatch_rank" not in entry
