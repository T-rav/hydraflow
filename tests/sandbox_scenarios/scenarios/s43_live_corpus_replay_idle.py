"""s43 - LiveCorpusReplayLoop idles with an empty shadow corpus.

Golden path: the sandbox runtime starts the real ``LiveCorpusReplayLoop`` with
the default empty shadow corpus. The loop should complete without filing drift
issues and emit a ``live_corpus_replay`` worker-status event.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s43_live_corpus_replay_idle"
DESCRIPTION = "LiveCorpusReplayLoop idles on an empty shadow corpus."


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["live_corpus_replay"],
        cycles_to_run=2,
    )


async def assert_outcome(api, page) -> None:
    """Verify a BACKGROUND_WORKER_STATUS event was emitted by the loop."""
    events_payload = await api.wait_until(
        "/api/events",
        lambda payload: any(
            isinstance(payload, list)
            and event.get("type") == "background_worker_status"
            and event.get("data", {}).get("worker") == "live_corpus_replay"
            for event in (payload if isinstance(payload, list) else [])
        ),
        timeout=60.0,
    )

    worker_events = [
        event
        for event in events_payload
        if event.get("type") == "background_worker_status"
        and event.get("data", {}).get("worker") == "live_corpus_replay"
    ]
    assert len(worker_events) >= 1, (
        "Expected at least one live_corpus_replay worker-status event; "
        f"got none. All events: {events_payload!r}"
    )
