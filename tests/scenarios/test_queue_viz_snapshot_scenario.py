"""MockWorld scenario: the pipeline snapshot carries the strategy visualisation
data end-to-end (#10067).

The unit tier (``tests/test_issue_store_snapshot_priority.py``) proves
``_snapshot_queued`` enriches entries; the vitest tier proves the board renders
the badge/chips/order. This tier proves the seam between them — that priority
and ``dispatch_rank`` survive the *real* ``IssueStore.get_pipeline_snapshot``
path a MockWorld harness drives, which is what ``GET /api/pipeline`` and the
``PIPELINE_SNAPSHOT`` push actually serialise. If the enrichment were dropped
somewhere between routing and snapshotting, the board would silently fall back
to unlabelled arrival order with every unit test still green.
"""

from __future__ import annotations

from unittest.mock import AsyncMock

from events import EventBus
from issue_store import STAGE_READY, IssueStore
from queue_strategy import QueueStrategy
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory


def _store(strategy: QueueStrategy) -> IssueStore:
    config = ConfigFactory.create()
    config.queue_strategy = strategy
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    return IssueStore(config, fetcher, EventBus())


def _enqueue(store: IssueStore, id: int, priority: str | None = None) -> None:
    tags = ["hydraflow-ready"] + ([priority] if priority else [])
    task = TaskFactory.create(id=id, tags=tags)
    store._queues[STAGE_READY].append(task)
    store._queue_members[STAGE_READY].add(task.id)


def test_snapshot_carries_priority_and_dispatch_rank_through_the_real_path() -> None:
    store = _store(QueueStrategy.WEIGHTED_MIX)
    _enqueue(store, 1, "P2")
    _enqueue(store, 2)
    _enqueue(store, 3, "P0")

    entries = store.get_pipeline_snapshot()[STAGE_READY]
    by_number = {e["issue_number"]: e for e in entries}

    # The P0 sits at dispatch rank 0 even though it arrived last, and every
    # entry carries its band — the two facts the board needs to show the badge,
    # the chips, and dispatch order.
    assert by_number[3]["priority"] == "P0"
    assert by_number[3]["dispatch_rank"] == 0
    assert by_number[1]["priority"] == "P2"
    assert by_number[2]["priority"] == "none"


def test_snapshot_dispatch_order_matches_the_active_strategy() -> None:
    # Under fifo the ranks follow arrival; the same seeded backlog under
    # weighted_mix does not. Proving both through the snapshot (not just the
    # engine) pins that the store hands the board strategy-aware ranks.
    ids = [(10, "P2"), (11, "P0"), (12, "P1")]

    fifo = _store(QueueStrategy.FIFO)
    for i, p in ids:
        _enqueue(fifo, i, p)
    fifo_order = sorted(
        fifo.get_pipeline_snapshot()[STAGE_READY], key=lambda e: e["dispatch_rank"]
    )
    assert [e["issue_number"] for e in fifo_order] == [10, 11, 12]

    weighted = _store(QueueStrategy.PRIORITY)
    for i, p in ids:
        _enqueue(weighted, i, p)
    weighted_order = sorted(
        weighted.get_pipeline_snapshot()[STAGE_READY], key=lambda e: e["dispatch_rank"]
    )
    assert [e["issue_number"] for e in weighted_order] == [11, 12, 10]
