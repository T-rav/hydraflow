"""s95 — the retrospective reports evidence counters, not a constant zero.

The loop used to return a hardcoded ``patterns_filed: 0`` from
``_handle_retro_patterns`` regardless of what it filed, so its published
details were a constant (#11890). This scenario proves the evidence-grounded
result shape survives the whole way out to ``/api/events``: through the loop's
own publish path, the event bus, and the dashboard API.

Unit tests see the dict the loop returns. Only this layer sees what a reader
of the running system actually gets.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s95_retro_evidence_counters"
DESCRIPTION = "RetrospectiveLoop publishes evidence counters, not a constant zero."

_EXPECTED_COUNTERS = ("patterns_filed", "findings_dropped", "signals_seen")


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["retrospective"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """The published details must carry every evidence counter."""

    def _retro_status_events(payload) -> list:
        if not isinstance(payload, list):
            return []
        return [
            event
            for event in payload
            if event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "retrospective"
        ]

    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: bool(_retro_status_events(payload)),
        timeout=60.0,
    )

    retro_events = _retro_status_events(events_payload)
    assert retro_events, (
        f"no retrospective worker-status event reached /api/events; "
        f"got {events_payload!r}"
    )

    # Any tick that ran the queue publishes details; find one that did.
    with_details = [e for e in retro_events if e.get("data", {}).get("details")]
    assert with_details, (
        "every retrospective status event published empty details — the loop "
        f"result never reached the API. Events: {retro_events!r}"
    )

    details = with_details[-1]["data"]["details"]
    missing = [key for key in _EXPECTED_COUNTERS if key not in details]
    assert not missing, (
        f"retrospective published details without {missing}. A reader of the "
        "running system cannot distinguish 'filed nothing' from 'never "
        f"counted'. Details: {details!r}"
    )
