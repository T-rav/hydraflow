"""s80 - ErosionMetricsLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``ErosionMetricsLoop`` and
an idle cycle (no seeded commit-range state) completes without error,
proving the loop is registered, wired through all the checkpoints, and
heartbeating in the real Docker stack (#10107, epic #10104: v1
change-spread/concept-scatter drift caretaker).

The threshold-gate / dedup-by-SHA / dedup-by-finding-fingerprint /
issue-filing behavior itself is covered by the Tier-1 MockWorld scenario in
``tests/scenarios/test_erosion_metrics_scenario.py`` (a real tiny git repo
fixture drives the change-spread/concept-scatter sensors end-to-end) —
that isn't yet expressible via ``MockWorldSeed`` (no seeded-git-history
field), so this Tier-2 layer stays scoped to proving the loop actually
runs inside the container, matching the idle-poll pattern used by
s47-s50/s74 for other caretaker loops.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s80_erosion_metrics_idle_poll"
DESCRIPTION = "ErosionMetricsLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["erosion_metrics"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by ErosionMetricsLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "erosion_metrics"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "erosion_metrics"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one erosion_metrics worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
