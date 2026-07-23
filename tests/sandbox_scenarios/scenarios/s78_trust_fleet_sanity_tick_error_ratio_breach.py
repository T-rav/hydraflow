"""s78 — TrustFleetSanityLoop's tick_error_ratio detector fires off seeded
worker-status event HISTORY (#10133, deferred from #9544).

Closes the read-side half of the #9643/#10086 materializer family: a seeded
``worker_heartbeats`` entry answers HealthMonitorLoop's dead-man-switch
staleness read (``state.get_worker_heartbeats()``), but
``TrustFleetSanityLoop._collect_window_metrics`` — the anomaly detectors'
24h ticks/repair/error window — reads through ``EventBus.load_events_since``,
a DISK read (``EventLog.load``), not the in-memory ``EventBus._history`` list
``worker_heartbeats`` never touches. The sandbox's shared bus has historically
been a bare ``EventBus()`` with no ``EventLog`` attached, so that read always
returned nothing regardless of what a scenario seeded — the
issues_per_hour / repair_ratio / tick_error_ratio breach paths had no
active-trigger coverage at all, docker or in-process.

The seed here gives ``corpus_learning`` (one of the nine §4.1–§4.9 watched
trust loops) five BACKGROUND_WORKER_STATUS rows spread across the loop's
full 24h window (23h/18h/12h/6h/1h ago) — four errored, one ok. That clears
both the tick_error_ratio threshold (0.2, ratio here is 0.8) and its
min-sample floor (3, sample here is 5), and deliberately spans nearly the
whole day rather than clustering in the last hour, so the scenario also
proves the loop's day_cutoff window genuinely reaches back that far, not
just its narrower issues_filed_hour bucket.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s78_trust_fleet_sanity_tick_error_ratio_breach"
DESCRIPTION = (
    "TrustFleetSanityLoop files a tick_error_ratio escalation for a watched "
    "trust loop whose seeded ~24h BACKGROUND_WORKER_STATUS history skews "
    "mostly errored, not just an idle heartbeat poll."
)

_WORKER = "corpus_learning"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["trust_fleet_sanity"],
        cycles_to_run=2,
        worker_status_history={
            _WORKER: [
                {"age_seconds": 82_800, "status": "error", "details": {}},  # ~23h
                {"age_seconds": 64_800, "status": "error", "details": {}},  # ~18h
                {"age_seconds": 43_200, "status": "error", "details": {}},  # ~12h
                {"age_seconds": 21_600, "status": "error", "details": {}},  # ~6h
                {"age_seconds": 3_600, "status": "ok", "details": {}},  # ~1h
            ],
        },
    )


async def assert_outcome(api, page) -> None:
    """A trust_fleet_sanity cycle escalates the seeded tick_error_ratio breach."""

    def _escalated(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "trust_fleet_sanity"
            and (e.get("data", {}).get("details") or {}).get("filed", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _escalated, timeout=90.0)

    sanity_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "trust_fleet_sanity"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("filed", 0) >= 1
        for e in sanity_events
    ), (
        "Expected trust_fleet_sanity to file an escalation for the seeded "
        f"tick_error_ratio breach; worker events: {sanity_events!r}"
    )
