"""s75 — HealthMonitorLoop's dead-man-switch actually escalates a stalled worker.

Closes the #10086 gap: the seed could already express a stale
``worker_heartbeats`` entry (#9643/#9904), but ``HealthMonitorLoop
._check_worker_staleness`` only sweeps names present in a wired
``BGWorkerManager``'s ``registered_loop_names()`` — a heartbeat for an
unregistered name never traverses the restart/escalate logic at all, so the
generic loop-stall dead-man-switch's escalation path had no e2e coverage.

The seed now also materializes ``registered_workers`` (a lightweight
duck-typed ``BGWorkerManager`` registration, mirroring
``materialize_worker_heartbeats``'s pattern) so ``workspace_gc`` is both
registered AND far past its stall threshold (interval 5s, cycle_timeout 5s →
threshold 3*5+5 = 20s; the seeded heartbeat is 99_999s old). No ``restart_cb``
is wired (sandbox_main's minimal seam, same as production before the
orchestrator injects one), so ``bg_workers.restart()`` returns ``False`` and
the sweep escalates — files a ``loop-stalled`` issue and publishes a
``worker_stall`` ``SYSTEM_ALERT`` — on the very first stale cycle, not just a
heartbeat.
"""

from __future__ import annotations

from mockworld.seed import MockWorldSeed

NAME = "s75_worker_stall_escalation"
DESCRIPTION = (
    "HealthMonitorLoop's generic dead-man-switch escalates a seeded "
    "registered-but-stalled worker (worker_stall SYSTEM_ALERT + loop-stalled "
    "issue), not just a heartbeat."
)

_STALLED_WORKER = "workspace_gc"


def seed() -> MockWorldSeed:
    return MockWorldSeed(
        loops_enabled=["health_monitor"],
        cycles_to_run=2,
        registered_workers={
            _STALLED_WORKER: {"interval_seconds": 5, "cycle_timeout_seconds": 5},
        },
        worker_heartbeats={
            # threshold = 3 * 5 + 5 = 20s; 99_999s is far past it, regardless
            # of clock — the materializer back-dates this at boot.
            _STALLED_WORKER: {"status": "ok", "age_seconds": 99_999},
        },
    )


async def assert_outcome(api, page) -> None:
    """A health cycle escalates the seeded stall via a worker_stall alert."""

    def _escalated(payload: object) -> bool:
        events = payload if isinstance(payload, list) else []
        return any(
            e.get("type") == "system_alert"
            and e.get("data", {}).get("kind") == "worker_stall"
            and e.get("data", {}).get("source") == "health_monitor"
            and e.get("data", {}).get("worker") == _STALLED_WORKER
            for e in events
        )

    events_payload = await api.wait_until("/api/events", _escalated, timeout=90.0)

    alerts = [
        e
        for e in events_payload
        if e.get("type") == "system_alert"
        and e.get("data", {}).get("kind") == "worker_stall"
    ]
    assert any(
        a.get("data", {}).get("worker") == _STALLED_WORKER
        and a.get("data", {}).get("source") == "health_monitor"
        for a in alerts
    ), (
        f"Expected health_monitor to escalate the seeded stall for "
        f"{_STALLED_WORKER!r} (a worker_stall system_alert); "
        f"alerts: {alerts!r}"
    )
    # The alert carries the filed issue number, not just a bare signal.
    assert any(
        isinstance(a.get("data", {}).get("issue"), int) and a["data"]["issue"] > 0
        for a in alerts
    ), (
        f"Expected the worker_stall alert to carry a filed issue number; alerts: {alerts!r}"
    )
