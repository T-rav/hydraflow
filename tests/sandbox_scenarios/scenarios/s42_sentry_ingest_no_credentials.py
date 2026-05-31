"""s42 - SentryLoop skips cleanly without credentials and emits worker status.

Golden path: the sandbox runtime starts the real ``SentryLoop`` with the
default no-credential config. The loop must not file issues or crash; it
should report an idle ``sentry_ingest`` worker tick.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s42_sentry_ingest_no_credentials"
DESCRIPTION = "SentryLoop idles without credentials and emits worker status."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["sentry_ingest"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by SentryLoop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "sentry_ingest"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "sentry_ingest"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one sentry_ingest worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
