"""s71 — EpicMonitorLoop actively flags a stale epic and raises a SYSTEM_ALERT.

Active-trigger upgrade of the s27 idle poll (#9643, unblocking the #9543
remainder): the seed materializes an ``EpicState`` whose ``last_activity`` is
back-dated far past ``epic_stale_days`` (relative ``last_activity_age_days``,
so the seed never rots), so a monitor cycle must actually flag it — post the
stale-warning comment through PRPort and publish a ``system_alert`` sourced
``epic_monitor`` — not merely heartbeat. The epic is also seeded as an open
FakeGitHub issue so ``post_comment`` lands on a real record; ``child_issues``
stays empty so ``refresh_cache`` needs no child fetches. Nothing touches the
air-gapped network.

s27 keeps covering the idle/no-epics path; this scenario has its own NEW id
and issue number per the active-trigger convention.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s71_epic_monitor_stale_alert"
DESCRIPTION = (
    "EpicMonitorLoop flags a seeded far-past-activity epic "
    "(details.stale_count >= 1 + system_alert), not just a heartbeat."
)

# One constant issue number across the seeded issue, EpicState and assertions.
_EPIC = 7601


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["epic_monitor"],
        cycles_to_run=2,
        issues=[
            {
                # ``hydraflow-epic`` is not a pipeline lifecycle label, so the
                # epic is visible to epic machinery only — the pipeline's
                # store refresh never picks it up.
                "number": _EPIC,
                "title": "Epic: long-forgotten rollup",
                "body": "## Sub-issues\n\n(none yet)\n",
                "labels": ["hydraflow-epic"],
                "state": "open",
            },
        ],
        epic_states=[
            {
                "epic_number": _EPIC,
                "title": "Epic: long-forgotten rollup",
                # 3650 days >> any realistic epic_stale_days (default single
                # digits), so the epic is stale regardless of config drift.
                "last_activity_age_days": 3650,
                "child_issues": [],
            },
        ],
    )


async def assert_outcome(api, page) -> None:
    """A monitor cycle reports the stale epic and raises the system alert."""

    def _flagged(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "background_worker_status"
            and e.get("data", {}).get("worker") == "epic_monitor"
            and (e.get("data", {}).get("details") or {}).get("stale_count", 0) >= 1
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _flagged, timeout=90.0)

    monitor_events = [
        e
        for e in events_payload
        if e.get("type") == "background_worker_status"
        and e.get("data", {}).get("worker") == "epic_monitor"
    ]
    assert any(
        (e.get("data", {}).get("details") or {}).get("stale_count", 0) >= 1
        for e in monitor_events
    ), (
        f"Expected epic_monitor to flag the seeded stale epic #{_EPIC} "
        f"(details.stale_count >= 1); worker events: {monitor_events!r}"
    )

    alerts = [
        e
        for e in events_payload
        if e.get("type") == "system_alert"
        and e.get("data", {}).get("source") == "epic_monitor"
    ]
    assert any(a.get("data", {}).get("epic_number") == _EPIC for a in alerts), (
        f"Expected a system_alert sourced epic_monitor for epic #{_EPIC}; "
        f"alerts: {alerts!r}"
    )
