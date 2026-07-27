"""Regression guard for #10556 — operator loop-health count must be the registry.

The operator console's Vitals card showed a *fluctuating* loop-health count
while the factory ran (observed 55/55 → 33/33). Two compounding causes:

1. Frontend (fixed in ``src/ui/src/operator/model/vitals.js``): ``toVitals``
   derived the count from the bounded, newest-first WS *events* window — a
   moving window that shrinks as slow loops age out.
2. Backend (this guard): even reading the sticky ``backgroundWorkers`` slice,
   the slice only fills as loops *tick*. Slow loops (pricing-refresh,
   wiki-maint, RC-promotion — hours-long intervals) are absent for a long time,
   so the count climbs from a partial set instead of showing the full registry.

The backend fix seeds one ``BACKGROUND_WORKER_STATUS`` event for every
registered background loop at orchestrator start, so the sticky slice holds the
whole registry immediately and the count is accurate + stable from boot.

This guard asserts the boot seed emits exactly one status per *registered* loop
(``bg_loop_registry``) — not just the ones that have ticked — carrying the
``enabled`` flag, with disabled loops reporting a ``disabled`` status.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

import pytest

from events import EventType, HydraFlowEvent
from orchestrator import HydraFlowOrchestrator

if TYPE_CHECKING:
    from config import HydraFlowConfig


async def _capture_seed(orch: HydraFlowOrchestrator) -> list[HydraFlowEvent]:
    """Run the boot seed against a fresh orchestrator, capturing published events."""
    published: list[HydraFlowEvent] = []
    original_publish = orch._bus.publish

    async def capture_publish(event: HydraFlowEvent) -> None:
        published.append(event)
        await original_publish(event)

    orch._bus.publish = capture_publish  # type: ignore[method-assign]
    await orch._seed_background_worker_statuses()
    return [e for e in published if e.type == EventType.BACKGROUND_WORKER_STATUS]


@pytest.mark.asyncio
async def test_boot_seed_emits_one_status_per_registered_loop(
    config: HydraFlowConfig,
) -> None:
    """The seed covers the WHOLE registry, not just loops that have ticked."""
    orch = HydraFlowOrchestrator(config)
    registered = orch.registered_bg_loop_names()
    # Sanity: a freshly built orchestrator has no worker heartbeats yet — so if
    # the count came from ticks it would be zero, which is exactly the bug.
    assert orch.get_bg_worker_states() == {}
    assert len(registered) >= 60  # ~64 registry loops; guards against a gutted list

    seeded = await _capture_seed(orch)

    seeded_names = {e.data["worker"] for e in seeded}
    # Exactly one status per registered loop — the count is the registry.
    assert seeded_names == registered
    assert len(seeded) == len(registered)


@pytest.mark.asyncio
async def test_boot_seed_carries_enabled_flag_and_marks_disabled_loops(
    config: HydraFlowConfig,
) -> None:
    """Every seeded status carries `enabled`; disabled loops report `disabled`."""
    orch = HydraFlowOrchestrator(config)
    seeded = await _capture_seed(orch)

    by_worker = {e.data["worker"]: e.data for e in seeded}
    for name, data in by_worker.items():
        # The enabled flag is always present and matches the manager's view.
        assert "enabled" in data
        assert data["enabled"] == orch.is_bg_worker_enabled(name)
        # A never-run enabled loop is `pending` (counted, but not a healthy tick);
        # a disabled loop is `disabled`. Neither is `error`, so all count as ok.
        if data["enabled"]:
            assert data["status"] == "pending"
        else:
            assert data["status"] == "disabled"

    # `principles_audit` ships default-disabled (BGWorkerManager) → proves the
    # disabled branch is actually exercised, not vacuously true.
    assert by_worker["principles_audit"]["enabled"] is False
    assert by_worker["principles_audit"]["status"] == "disabled"
