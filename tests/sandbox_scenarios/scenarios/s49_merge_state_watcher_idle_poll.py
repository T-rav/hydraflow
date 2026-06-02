"""s49 - MergeStateWatcherLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``MergeStateWatcherLoop`` and an idle cycle
completes without error, proving the loop is registered, started, and
heartbeating in the real Docker stack. Closes part of #9155.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s49_merge_state_watcher_idle_poll"
DESCRIPTION = "MergeStateWatcherLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["merge_state_watcher"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by MergeStateWatcherLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "merge_state_watcher"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "merge_state_watcher"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one merge_state_watcher worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
