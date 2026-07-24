"""s87 - SecondOrderVitalsLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``SecondOrderVitalsLoop`` and
an idle cycle (no seeded instrument ledgers — every series reads absent, so the
verdict is an honest ``green (0-of-5 reporting)`` and no alarm fires) completes
without error, proving the capstone residual monitor is registered, wired
through all the checkpoints, and heartbeating in the real Docker stack (#10373:
the green-while-dying monitor over the falsification-instrument set).

The Shewhart control-limit math, the k-of-5 + sustained-window verdict logic,
the diverging → single find + HITL alarm, and the honest degrade-to-n-of-5 are
covered by the unit tests (``tests/test_second_order_vitals_control.py``,
``tests/test_second_order_vitals_verdict.py``,
``tests/test_second_order_vitals_loop.py``) and the Tier-1 MockWorld scenario
(``tests/scenarios/test_second_order_vitals_scenario.py``), which seeds adverse
drift across three families and drives the full path with an injected green
primary-health gate. Driving a real multi-window divergence through seeded
ledgers isn't yet expressible via ``MockWorldSeed`` (no seeded-ledger-history
field), so this Tier-2 layer stays scoped to proving the loop actually runs
inside the container — matching the idle-poll pattern used by s83/s84/s85/s86
for the sibling instruments. The loop spawns nothing, so it needs no air-gap
seam.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s87_second_order_vitals_idle_poll"
DESCRIPTION = "SecondOrderVitalsLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["second_order_vitals"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by SecondOrderVitalsLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "second_order_vitals"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "second_order_vitals"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one second_order_vitals worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
