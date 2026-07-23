"""s83 - EscapeLedgerLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``EscapeLedgerLoop`` and an
idle cycle (no seeded commit-range state — the cursor primes on the first
tick) completes without error, proving the loop is registered, wired through
all the checkpoints, and heartbeating in the real Docker stack (#10367: the
FOUNDATION falsification instrument — escape ledger + erosion trend surfaces).

The escape-detection / attribution / dedup-by-SHA / ledger-recording /
finding-rate-budget behavior itself is covered by the Tier-1 MockWorld
scenario in ``tests/scenarios/test_escape_ledger_scenario.py`` (a real tiny
git repo fixture drives a `git revert` range end-to-end) — that isn't yet
expressible via ``MockWorldSeed`` (no seeded-git-history field), so this
Tier-2 layer stays scoped to proving the loop actually runs inside the
container, matching the idle-poll pattern used by s74/s80 for other caretaker
loops.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s83_escape_ledger_idle_poll"
DESCRIPTION = "EscapeLedgerLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["escape_ledger"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by EscapeLedgerLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "escape_ledger"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "escape_ledger"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one escape_ledger worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
