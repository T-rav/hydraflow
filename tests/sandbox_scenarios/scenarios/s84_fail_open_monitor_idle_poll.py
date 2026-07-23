"""s84 - FailOpenMonitorLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``FailOpenMonitorLoop`` and an
idle cycle (no seeded fail-open ledger — a control limit needs several days of
history before it can fire, so an empty ledger idle-polls cleanly) completes
without error, proving the loop is registered, wired through all the
checkpoints, and heartbeating in the real Docker stack (#10371: judge-
independence budget + fail-visible dispatch — the fail-open RATE monitor).

This is the Tier-2 layer that catches boot/wiring breaks a real container hits
(the #10365 class: ``src`` importing ``scripts`` broke the boot). The Shewhart
control-limit computation, per-day breach dedup, and hydraflow-find filing are
covered by the Tier-1 unit tests (``tests/test_fail_open_monitor_loop.py``) and
the MockWorld scenario (``tests/scenarios/test_judge_independence_scenario.py``,
which seeds a spike ledger and drives a breach end-to-end through FakeGitHub) —
that spike ledger isn't yet expressible via ``MockWorldSeed`` (no seeded-
diagnostics-ledger field), so this layer stays scoped to proving the loop
actually boots + ticks inside the container, matching the idle-poll pattern
used by s80/s83 for the sibling caretaker loops.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s84_fail_open_monitor_idle_poll"
DESCRIPTION = "FailOpenMonitorLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["fail_open_monitor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by FailOpenMonitorLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "fail_open_monitor"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "fail_open_monitor"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one fail_open_monitor worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
