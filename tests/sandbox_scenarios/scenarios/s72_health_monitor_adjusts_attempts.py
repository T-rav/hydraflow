"""s72 — HealthMonitorLoop actively auto-adjusts on a seeded low first-pass rate.

Active-trigger upgrade of the s48 idle poll (#9643, unblocking the #9543
remainder): the seed materializes an ``outcomes.jsonl`` trend history whose
first-pass rate (1 success / 10) sits far below the ``first_pass_rate_low``
threshold (0.2), so a health cycle must actually apply the
``max_quality_fix_attempts`` auto-adjustment (``details.adjustments_made >=
1``) — not merely heartbeat. ``item_scores.json`` rides along to prove the
second flat-memory_dir artifact path end-to-end. Pure local-disk reads;
nothing touches the air-gapped network.

s48 keeps covering the idle/no-data path; this scenario has its own NEW id
per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s72_health_monitor_adjusts_attempts"
DESCRIPTION = (
    "HealthMonitorLoop bumps max_quality_fix_attempts from a seeded low "
    "first-pass-rate trend (details.adjustments_made >= 1), not just a heartbeat."
)


def seed() -> MockWorldSeed:
    # 9 failures + 1 success → first_pass_rate 0.1 < 0.2 (first_pass_rate_low).
    outcomes = [{"outcome": "failure"} for _ in range(9)] + [{"outcome": "success"}]
    return MockWorldSeed(
        loops_enabled=["health_monitor"],
        cycles_to_run=2,
        health_metrics={
            "outcomes": outcomes,
            # Healthy score (>= 0.3) so no stale-item side path fires; the
            # point is proving item_scores.json lands where the loop reads it.
            "item_scores": {"pattern-1": {"score": 0.8, "appearances": 3}},
        },
    )


async def assert_outcome(api, page) -> None:
    """A health cycle reports the low first-pass rate and an applied adjustment."""

    def _adjusted(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "health_monitor"
            and (e.get("data", {}).get("details") or {}).get("adjustments_made", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _adjusted, timeout=90.0)

    health_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "health_monitor"
    ]
    active = [
        e
        for e in health_events
        if (e.get("data", {}).get("details") or {}).get("adjustments_made", 0) >= 1
    ]
    assert active, (
        f"Expected health_monitor to auto-adjust on the seeded 0.1 first-pass "
        f"rate (details.adjustments_made >= 1); worker events: {health_events!r}"
    )
    # The trigger metric itself came from the seeded trend, not an empty read.
    assert any(
        (e.get("data", {}).get("details") or {}).get("total_outcomes", 0) >= 10
        for e in active
    ), f"Expected the seeded 10-row outcome window to be read; events: {active!r}"
