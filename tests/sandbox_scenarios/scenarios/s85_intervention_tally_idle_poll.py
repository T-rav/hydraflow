"""s85 - InterventionTallyLoop emits worker status for an idle poll.

Golden path: the sandbox runtime starts the real ``InterventionTallyLoop`` and
an idle cycle (no seeded human touches — the timestamp cursor primes on the
first tick) completes without error, proving the loop is registered, wired
through all the checkpoints, and heartbeating in the real Docker stack (#10369:
the attention-side telemetry instrument — interventions per 100 merges +
loops-per-governor).

The sense → classify → record / bounded-LLM-budget behavior itself is covered
by the Tier-1 MockWorld scenario in
``tests/scenarios/test_intervention_tally_scenario.py`` (a seeded event log +
steering map drive the full path, with the free-text LLM classifier injected
as a fake). The cheap-LLM classification path is deliberately unreachable in
the air-gapped sandbox — ``intervention_tally_classify_enabled`` is pinned OFF
(the ``intervention_tally_loop`` ``config_disable`` seam) — so this Tier-2
layer stays scoped to proving the loop actually runs inside the container,
matching the idle-poll pattern used by s83 for the sibling escape ledger.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s85_intervention_tally_idle_poll"
DESCRIPTION = "InterventionTallyLoop performs an idle scan and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["intervention_tally"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by InterventionTallyLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "intervention_tally"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "intervention_tally"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one intervention_tally worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
