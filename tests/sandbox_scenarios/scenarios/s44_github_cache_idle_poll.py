"""s44 - GitHubCacheLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``GitHubCacheLoop`` and the
MockWorld GitHub cache path completes an idle poll without hitting live GitHub.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s44_github_cache_idle_poll"
DESCRIPTION = "GitHubCacheLoop performs an idle poll and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["github_cache"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by GitHubCacheLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "github_cache"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "github_cache"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one github_cache worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
