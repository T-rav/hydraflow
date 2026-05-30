"""s41 — BranchProtectionAuditorLoop ticks and emits a worker-status event.

Golden path: the loop runs in the real sandboxed app, audits live branch
protection against the canonical rulesets, and emits a BACKGROUND_WORKER_STATUS
event for ``branch_protection_auditor`` — proving the caretaker-registry +
loop-factory wiring (ADR-0082, ADR-0029) is intact end-to-end.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s41_branch_protection_auditor_no_drift"
DESCRIPTION = (
    "BranchProtectionAuditorLoop ticks against the canonical rulesets → emits "
    "a worker-status event, proving caretaker-registry wiring is intact."
)


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["branch_protection_auditor"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by the loop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "branch_protection_auditor"
            for e in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "branch_protection_auditor"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one branch_protection_auditor worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
