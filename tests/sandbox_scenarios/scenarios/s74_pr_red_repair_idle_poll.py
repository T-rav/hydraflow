"""s71 - PrRedRepairLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``PrRedRepairLoop`` and an
idle cycle (no open PRs seeded) completes without error, proving the loop
is registered, wired through all seven checkpoints, and heartbeating in
the real Docker stack (#10027 Phase 1: infra-flake retrier).

The settled-red-detect -> bounded-rerun behavior itself (including the
mid-rerun stale-conclusion trap) is covered by the Tier-1 MockWorld
scenario in ``tests/scenarios/test_pr_red_repair_scenario.py`` — seeding a
workflow run + jobs isn't yet expressible via ``MockWorldSeed`` (no
``workflow_runs`` field), so this Tier-2 layer stays scoped to proving the
loop actually runs inside the container, matching the idle-poll pattern
used by s47-s50 for other caretaker loops.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s74_pr_red_repair_idle_poll"
DESCRIPTION = "PrRedRepairLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["pr_red_repair"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by PrRedRepairLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "pr_red_repair"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "pr_red_repair"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one pr_red_repair worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
