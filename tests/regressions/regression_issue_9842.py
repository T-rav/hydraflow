"""Regression pins for issue #9842 — event-driven workstream cards.

Phase transitions swap the issue's GitHub pipeline label immediately
(``PRManager.swap_pipeline_labels``), but the dashboard's board rendered from
``IssueStore``'s label-derived queues, which only re-read GitHub at the
``data_poll_interval`` refresh (300s, ``config.py``) — so a finished phase's
card lagged up to ~5 minutes behind reality. The fix is "push on transition,
poll for truth": ``swap_pipeline_labels`` notifies an injected listener
(``IssueStore.apply_label_transition``), which applies the move to the
in-memory pipeline eagerly and lets the existing coalesced PIPELINE_SNAPSHOT
push (0.1s debounce) carry it over the WebSocket within ~1s. The 300s poll
stays as the reconciling backstop; the eager-transition protection prevents a
stale poll from dragging the card backward.

Invariants pinned here:

1. **A label swap moves the card without any store refresh.** With PRManager
   and IssueStore wired the way ``service_registry.build_services`` wires
   them, ``swap_pipeline_labels`` alone must produce a live PIPELINE_SNAPSHOT
   frame showing the issue in its new stage — no ``refresh()`` (the 300s
   poll) in between. If this pin fails, cards are poll-bound again.

2. **The stale poll cannot undo the eager move.** The reconciling refresh may
   run with pre-swap label data (the GitHub cache is up to 5 minutes old);
   the issue must stay in the swapped stage.
"""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import AsyncMock

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "src"))

from events import EventBus, EventType
from issue_store import STAGE_READY, STAGE_REVIEW, IssueStore
from tests.conftest import TaskFactory
from tests.helpers import ConfigFactory, make_pr_manager


def _make_wired_pair(event_bus: EventBus) -> tuple[IssueStore, object]:
    """A real IssueStore + real PRManager wired like build_services does."""
    config = ConfigFactory.create()
    fetcher = AsyncMock()
    fetcher.fetch_all = AsyncMock(return_value=[])
    store = IssueStore(config, fetcher, event_bus)
    mgr = make_pr_manager(config, event_bus)
    # gh label mutations are not under test — stub the network edge only.
    mgr._add_labels_strict = AsyncMock()
    mgr._remove_label = AsyncMock()
    mgr.set_pipeline_label_listener(store.apply_label_transition)
    return store, mgr


@pytest.mark.asyncio
async def test_label_swap_pushes_the_new_stage_without_a_poll() -> None:
    bus = EventBus()
    store, mgr = _make_wired_pair(bus)
    subscriber = bus.subscribe()
    issue = TaskFactory.create(id=9842, tags=["test-label"])  # ready stage
    store._route_issues([issue])

    await mgr.swap_pipeline_labels(9842, "hydraflow-review")

    # Drain the coalesced snapshot flush — the ONLY thing between the swap
    # and the WS frame. Crucially: store.refresh() is never called.
    flush = store._snapshot_flush_task
    assert flush is not None, "label swap did not schedule a snapshot flush"
    await flush

    frames = []
    while not subscriber.empty():
        event = subscriber.get_nowait()
        if event.type == EventType.PIPELINE_SNAPSHOT:
            frames.append(event)
    assert frames, "no live PIPELINE_SNAPSHOT frame after the label swap"
    stages = frames[-1].data["stages"]
    assert 9842 in [e["issue_number"] for e in stages["review"]]
    assert 9842 not in [e["issue_number"] for e in stages["implement"]]


@pytest.mark.asyncio
async def test_stale_reconciling_poll_does_not_drag_the_card_backward() -> None:
    bus = EventBus()
    store, mgr = _make_wired_pair(bus)
    issue = TaskFactory.create(id=9843, tags=["test-label"])  # ready stage
    store._route_issues([issue])

    await mgr.swap_pipeline_labels(9843, "hydraflow-review")
    # The next poll serves 5-minute-old labels that still say "ready".
    store._route_issues([TaskFactory.create(id=9843, tags=["test-label"])])

    assert 9843 in store._queue_members[STAGE_REVIEW]
    assert 9843 not in store._queue_members[STAGE_READY]
