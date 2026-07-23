"""s50 - DisturbanceDampenerLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``DisturbanceDampenerLoop``
and an idle cycle (no runner/PR-manager wiring, empty backlog) completes
without error, proving the loop is registered, started, and heartbeating in
the real Docker stack. Real suppression burn-down + PR-opening behavior is
already covered by the MockWorld scenario (Task 4); this sandbox scenario
exists to catch docker/UI/wiring regressions only.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s50_disturbance_dampener_idle_poll"
DESCRIPTION = "DisturbanceDampenerLoop performs an idle poll and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["disturbance_dampener"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by disturbance_dampener."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "disturbance_dampener"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "disturbance_dampener"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one disturbance_dampener worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
