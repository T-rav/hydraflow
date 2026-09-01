"""A loop with work in flight is not stalled.

The health snapshot measured a loop's age from its last **completed** tick:
`update_bg_worker_status(name, "ok")` fires after `work_fn()` returns. For a
loop that dispatches a long agent run — `plan` on a large issue, `triage` on a
batch — the completion stamp stays hours old for the entire run, and
`age > stall_multiplier * interval` is true the whole time.

Observed live on 2026-09-01. Three consecutive supervisor observations reported
`healthy: false` with 3, then 9, then 4 stalled loops, every time with
`error_loops: []`, `event_loop_stalled: false` and `vitals_verdict: green`. The
supervisor's own assessment named the shape without being able to act on it:

    "a correlated mass stall pointing at a shared scheduler/heartbeat cause
     rather than nine independent wedges"

The shared cause was the measurement. At 03:53 the snapshot listed `plan` as
stalled; at 03:54 the event stream carried planner transcript lines for issue
#11544. It was working.

**Wedge detection is not lost.** A tick that is genuinely stuck is cancelled by
the per-cycle watchdog and surfaces in `error_loops` — the signal that already
means "wedged" (see `pattern_supervisor_pending_blind_spot`: a supervisor
cannot tell slow from stuck without an explicit timeout, and the timeout is
where that judgement belongs, not the heartbeat age).
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

import pytest

from supervisor_observation import build_health_snapshot

_NOW = datetime(2026, 9, 1, 3, 53, 0, tzinfo=UTC)


def _hb(status: str, *, hours_ago: float) -> dict[str, str]:
    return {
        "status": status,
        "last_run": (_NOW - timedelta(hours=hours_ago)).isoformat(),
    }


def test_a_loop_with_a_tick_in_flight_is_not_stalled() -> None:
    """The live shape: `plan` mid-run, completion stamp hours old."""
    snap = build_health_snapshot(
        heartbeats={"plan": _hb("running", hours_ago=10)},
        intervals={"plan": 30},
        stall_multiplier=4,
        now=_NOW,
    )

    assert snap.stalled_loops == [], (
        "a loop actively running a tick was reported stalled — its completion "
        "stamp is necessarily stale while it works"
    )
    assert snap.healthy is True


def test_an_idle_loop_past_its_interval_is_still_stalled() -> None:
    """Anti-vacuity: the guard must not disable stall detection.

    Without this, marking every loop `running` forever would satisfy the test
    above while removing the signal entirely.
    """
    snap = build_health_snapshot(
        heartbeats={"triage": _hb("ok", hours_ago=10)},
        intervals={"triage": 30},
        stall_multiplier=4,
        now=_NOW,
    )

    assert snap.stalled_loops == ["triage"]
    assert snap.healthy is False


def test_a_running_loop_that_errored_is_still_reported() -> None:
    """`running` suppresses STALLED, never ERROR.

    A wedged tick is cancelled by the per-cycle watchdog and arrives here as
    `error`. If `running` swallowed that too, the fix would trade a false
    positive for a false negative on the signal that actually matters.
    """
    snap = build_health_snapshot(
        heartbeats={"repo_wiki": _hb("error", hours_ago=10)},
        intervals={"repo_wiki": 30},
        stall_multiplier=4,
        now=_NOW,
    )

    assert snap.error_loops == ["repo_wiki"]
    assert snap.healthy is False


@pytest.mark.parametrize("status", ["disabled", "running"])
def test_the_never_stalled_statuses_are_exactly_these(status: str) -> None:
    """Both exemptions, by the same rule, so neither drifts alone."""
    snap = build_health_snapshot(
        heartbeats={"x": _hb(status, hours_ago=99)},
        intervals={"x": 1},
        stall_multiplier=1,
        now=_NOW,
    )
    assert snap.stalled_loops == []


def test_running_is_a_declared_health_member_not_a_bare_string() -> None:
    """`_normalise_worker_health` coerces UNKNOWN statuses to DISABLED.

    A `running` heartbeat that is not an enum member would therefore render as
    a disabled worker in the dashboard — the loop would vanish from the panel
    exactly while it was busiest.
    """
    from models import BGWorkerHealth

    assert BGWorkerHealth("running") is BGWorkerHealth.RUNNING


# ---------------------------------------------------------------------------
# The wiring. The snapshot fix above is inert without a producer of `running`.
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_the_polling_loop_marks_the_tick_in_flight_before_working() -> None:
    """`_polling_loop` must emit `running` BEFORE calling work_fn.

    Asserted at the seam rather than on the snapshot, because the snapshot is
    already correct and always was — the defect was that nothing ever set
    `running`. A test of the pure predicate passes whether or not the producer
    exists: removing the `update_bg_worker_status(name, "running")` call
    reddens nothing without this test, which is the exact vacuous-wiring shape
    that keeps recurring here.

    Ordering matters as much as presence: a `running` stamp written after the
    work would record liveness the loop had already demonstrated by finishing,
    and would leave the in-flight window — the whole problem — uncovered.
    """
    import asyncio

    from config import HydraFlowConfig
    from orchestrator import HydraFlowOrchestrator

    config = HydraFlowConfig(repo="owner/repo")
    orch = HydraFlowOrchestrator(config)

    seen: list[tuple[str, str]] = []
    orch.update_bg_worker_status = lambda name, status, **_kw: seen.append(  # type: ignore[method-assign]
        (name, status)
    )

    async def work() -> bool:
        seen.append(("work", "ran"))
        orch._stop_event.set()
        return False

    async def instant_sleep(seconds: int) -> None:  # noqa: ARG001
        await asyncio.sleep(0)

    orch._sleep_or_stop = instant_sleep  # type: ignore[method-assign]
    await orch._polling_loop("plan", work, 10)

    assert ("plan", "running") in seen, (
        "the polling loop never marked the tick in flight — the snapshot's "
        f"`running` exemption has no producer and is dead code: {seen}"
    )
    assert seen.index(("plan", "running")) < seen.index(("work", "ran")), (
        f"`running` was recorded after the work, not before it: {seen}"
    )
    assert ("plan", "ok") in seen, "the completion heartbeat was lost"
