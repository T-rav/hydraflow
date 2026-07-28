"""Regression guard for #10751 — boot-seed error replays must be marked seeded.

A sampled adversarial re-audit of PR #10739 (the #10556 loop-count stability
fix) found a silent escape: ``orchestrator._seed_background_worker_statuses``
republishes each loop's *persisted* last status as a fresh
``BACKGROUND_WORKER_STATUS`` event at boot, including ``error`` when a loop's
last known state before the restart was a failure. The operator console's
restart tally (``vitals.js`` ``errorCountByLoop``) counts every
``background_worker_status`` event with ``status == "error"`` in the WS event
window, with no way to tell a replayed persisted state from a real-time
failure — so every orchestrator restart phantom-inflates the Restarts panel
for any loop that happened to be in error when the process stopped, even
though nothing failed in the new session.

The fix tags every seeded event with ``seeded=True`` so the restart tally can
exclude boot replays while the loop's current status still counts toward
loop-health. This guard pins the backend half: a *restored-error* loop is
seeded with ``status="error"`` AND ``seeded=True`` (the existing #10556 guard
only ever exercised a freshly-constructed orchestrator with empty states, so
it never covered the restored-error path).
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from events import EventType, HydraFlowEvent
from orchestrator import HydraFlowOrchestrator

if TYPE_CHECKING:
    from config import HydraFlowConfig


async def _capture_seed(orch: HydraFlowOrchestrator) -> list[HydraFlowEvent]:
    """Run the boot seed against *orch*, capturing published status events."""
    published: list[HydraFlowEvent] = []
    original_publish = orch._bus.publish

    async def capture_publish(event: HydraFlowEvent) -> None:
        published.append(event)
        await original_publish(event)

    orch._bus.publish = capture_publish  # type: ignore[method-assign]
    await orch._seed_background_worker_statuses()
    return [e for e in published if e.type == EventType.BACKGROUND_WORKER_STATUS]


@pytest.mark.asyncio
async def test_every_seeded_event_is_marked_seeded(config: HydraFlowConfig) -> None:
    """All boot-seed replays carry ``seeded=True`` so consumers can exclude them."""
    orch = HydraFlowOrchestrator(config)
    seeded = await _capture_seed(orch)

    assert seeded, "boot seed emitted no status events"
    assert all(e.data.get("seeded") is True for e in seeded)


@pytest.mark.asyncio
async def test_restored_error_is_seeded_error_not_a_live_restart(
    config: HydraFlowConfig,
) -> None:
    """A loop in error at last shutdown replays as a seeded error, not live.

    The status is preserved (``error`` still counts toward loop-health) but the
    ``seeded`` flag lets the restart window drop it — otherwise the operator
    Restarts panel over-counts by one on every restart for that loop.
    """
    orch = HydraFlowOrchestrator(config)

    # Simulate a loop that failed its last cycle before the process stopped:
    # its persisted heartbeat is `error`, restored into `_bg_worker_states`.
    boom = next(
        n for n in sorted(orch.registered_bg_loop_names()) if orch.is_bg_worker_enabled(n)
    )
    orch._bg_workers.update_status(boom, "error")

    seeded = await _capture_seed(orch)
    by_worker = {e.data["worker"]: e.data for e in seeded}

    # The restored error status is faithfully replayed...
    assert by_worker[boom]["status"] == "error"
    # ...but explicitly marked as a boot replay, not a fresh live failure.
    assert by_worker[boom]["seeded"] is True
