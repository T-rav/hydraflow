"""s76 — pipeline_poller emits a PIPELINE_STATS event.

``pipeline_poller`` is the orchestrator-level ``_pipeline_stats_loop``
(src/orchestrator.py ~965), NOT a ``BaseBackgroundLoop`` subclass — it is a
hand-rolled ``while`` loop started directly from
``HydraFlowOrchestrator``'s ``loop_factories`` list. It reports its heartbeat
via ``BGWorkerManager.update_status`` (state only — no
``BACKGROUND_WORKER_STATUS`` event), but each cycle it genuinely calls
``orchestrator.emit_pipeline_stats()``, which publishes a ``PIPELINE_STATS``
event (``EventType.PIPELINE_STATS`` == ``"pipeline_stats"``,
src/events.py:86) onto the shared event bus (#9441).

Because it is not in ``bg_loop_registry`` (only the caretaker/phase loops
are), the docker sandbox always starts it as part of
``HydraFlowOrchestrator.run()`` regardless of this scenario's
``loops_enabled`` — its default cadence is 5 seconds
(``bg_worker_manager.py``'s ``non_loop_defaults["pipeline_poller"] = 5``), so
a PIPELINE_STATS event lands well within this scenario's poll timeout.

``loops_enabled=["pipeline_poller"]`` still matters for the Tier-1 in-process
parity test (``tests/scenarios/test_sandbox_parity.py``): it selects the
``run_with_loops`` path, whose special case for this name drives the real
``orchestrator.emit_pipeline_stats()`` instead of trying (and failing) to
``LoopCatalog.instantiate("pipeline_poller")``.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s76_pipeline_poller_emits_stats"
DESCRIPTION = (
    "pipeline_poller (orchestrator-level _pipeline_stats_loop, not a "
    "BaseBackgroundLoop) emits a PIPELINE_STATS event each cycle."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["pipeline_poller"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a PIPELINE_STATS event was published by pipeline_poller.

    Scans the full ``/api/events`` history (not just the latest event) —
    pipeline_poller publishes on every cycle, so any single event in the
    history proves the emitter is wired end to end.
    """
    _ = page  # UI interaction not needed for this event-emission assertion

    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list) and event.get("type") == "pipeline_stats"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    stats_events = [
        event for event in events_payload if event.get("type") == "pipeline_stats"
    ]
    assert len(stats_events) >= 1, (
        "Expected at least one pipeline_stats event from pipeline_poller; "
        f"got none. All events: {events_payload!r}"
    )
