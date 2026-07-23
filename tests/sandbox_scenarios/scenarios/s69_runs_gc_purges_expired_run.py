"""s69 — RunsGCLoop actively purges an expired run artifact.

Active-trigger upgrade of the s47 idle poll (#9543): the seed materializes a
run-artifact directory back-dated far past ``artifact_retention_days``
(RunRecorder derives artifact age from the ``%Y%m%dT%H%M%SZ`` directory
name), so a GC cycle must actually delete it — not merely heartbeat. Pure
local-disk work; nothing touches the air-gapped network.

s47 keeps covering the idle/nothing-expired path; this scenario has its own
NEW id and issue number per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s69_runs_gc_purges_expired_run"
DESCRIPTION = (
    "RunsGCLoop purges a seeded, far-past-retention run directory "
    "(details.expired_purged >= 1), not just a heartbeat."
)

# One constant issue number across the seeded run dir and the assertions.
_ISSUE = 7501


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["runs_gc"],
        cycles_to_run=2,
        # 3650 days ≫ any realistic artifact_retention_days (default 30), so
        # the seeded run is expired regardless of config drift.
        expired_run_dirs=[{"issue": _ISSUE, "age_days": 3650}],
    )


async def assert_outcome(api, page) -> None:
    """A runs_gc cycle reports at least one expired run purged."""

    def _purged(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "runs_gc"
            and (e.get("data", {}).get("details") or {}).get("expired_purged", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _purged, timeout=90.0)

    gc_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "runs_gc"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("expired_purged", 0) >= 1
        for e in gc_events
    ), (
        f"Expected runs_gc to purge the seeded expired run for issue "
        f"#{_ISSUE} (details.expired_purged >= 1); worker events: {gc_events!r}"
    )
