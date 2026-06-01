"""s45 — GateActivatorLoop ticks and emits a worker-status event.

Golden path: the loop runs in the real sandboxed app, scans the gate contract
for planned gates whose protected surface now exists, and emits a
BACKGROUND_WORKER_STATUS event for ``gate_activator`` — proving the
caretaker-registry + loop-factory wiring (ADR-0082, ADR-0029) is intact
end-to-end. The sandbox repo's gates are all active, so no issue is filed; this
exercises the idle/steady-state path.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s45_gate_activator_no_proposals"
DESCRIPTION = (
    "GateActivatorLoop ticks against the gate contract → emits a worker-status "
    "event, proving caretaker-registry wiring is intact."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["gate_activator"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by the loop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "gate_activator"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "gate_activator"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one gate_activator worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
