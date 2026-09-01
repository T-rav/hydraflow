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

    def _any_with_details(payload) -> bool:
        return any(
            event.get("data", {}).get("details")
            for event in _retro_status_events(payload)
        )

    # Wait for a tick that PUBLISHED, not merely for the loop to exist. The
    # first status event a seeded loop emits is `status: pending` with empty
    # details, so waiting on "any retrospective event" returned immediately and
    # the assertions below fired against a loop that had not run yet — a
    # guaranteed failure dressed as a flake.
    #
    # TimeoutError is caught rather than propagated so the diagnostics below
    # still produce their message; `wait_until` raises with only the raw
    # payload, which says nothing about which counter was missing.
    try:
        events_payload = await api.wait_until(
            "/api/events", _any_with_details, timeout=60.0
        )
    except TimeoutError:
        events_payload = await api.get("/api/events")

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
