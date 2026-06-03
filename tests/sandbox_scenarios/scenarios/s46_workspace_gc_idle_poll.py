"""s46 - WorkspaceGCLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``WorkspaceGCLoop`` and a GC
cycle completes (no stale worktrees/branches to collect) without error, proving
the loop is registered, started, and heartbeating in the real Docker stack.
Closes part of #9155 (worker-fleet e2e backfill).
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s46_workspace_gc_idle_poll"
DESCRIPTION = "WorkspaceGCLoop performs an idle GC cycle and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["workspace_gc"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by WorkspaceGCLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "workspace_gc"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "workspace_gc"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one workspace_gc worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
