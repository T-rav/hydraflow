"""Regression pins for #11604 — a starved host must not hard-restart the factory.

The incident: the thread-level freeze detector (#9552 / ADR-0106) tripped at
120.9s and, with ``event_loop_watchdog_hard_restart`` armed, exited the
process. The stack dump named ``trust_fleet_sanity_loop._collect_window_metrics``
— but measurement showed that tally walks at most ``max_events`` (5000) events
and costs ~1.8 ms, four orders of magnitude short of a 120s block. The host was
simultaneously running two ``pytest -n auto`` suites and a docker stack: the
loop was STARVED, not blocked, and the restart made a busy host busier.

Two pins, one per half of the fix:

1. **Escalation robustness** — the destructive path (``os._exit``) is now
   gated on (a) the freeze not being classified as host starvation and (b) the
   marker's ``episode_count`` reaching ``event_loop_watchdog_restart_after_
   episodes``. The NOTIFY path (dump + marker + issue) stays sensitive on the
   first episode, whatever the verdict.
2. **The tally's bound** — ``EventLog._load_sync`` applies ``max_events``
   AFTER the ``since`` filter, so the on-loop tally is bounded regardless of
   how large ``events.jsonl`` grows. Lifting that cap would reintroduce an
   unbounded on-loop walk.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from pathlib import Path

from event_loop_watchdog import (
    EVENT_LOOP_STALL_EXIT_CODE,
    FREEZE_BLOCKED,
    FREEZE_STARVED,
    EventLoopWatchdog,
    classify_freeze,
    may_hard_restart,
    read_stall_marker,
)


class _SteppingClock:
    """Deterministic monotonic clock — advanced explicitly by the test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _watchdog(
    tmp_path: Path,
    *,
    clock: _SteppingClock,
    exit_calls: list[int],
    starvation_ratio: float = 0.5,
    restart_after: int = 2,
) -> EventLoopWatchdog:
    return EventLoopWatchdog(
        stall_seconds_cb=lambda: 100.0,
        hard_restart_cb=lambda: True,
        restart_after_episodes_cb=lambda: restart_after,
        starvation_service_ratio_cb=lambda: starvation_ratio,
        diagnostics_dir=tmp_path / "diagnostics",
        poll_seconds=1.0,
        clock=clock,
        cpu_clock=lambda: 0.0,  # process burns no CPU: not a spin
        exit_fn=exit_calls.append,
        dump_fn=lambda _p: None,
    )


def _poll_through(
    wd: EventLoopWatchdog, clock: _SteppingClock, seconds: float, *, poll: float = 1.0
) -> None:
    """Advance *clock* in poll-sized steps, checking once per step.

    Faithful to the daemon thread's real cadence. A single giant clock jump
    would simulate a watchdog thread that itself stopped running — which is
    exactly the starvation signature the trip now discriminates against.
    """
    for _ in range(int(round(seconds / poll))):
        clock.advance(poll)
        wd._check_once()


# ---------------------------------------------------------------------------
# 1. The escalation decision core (pure, no threads, no clock)
# ---------------------------------------------------------------------------


def test_starved_host_is_not_classified_as_a_block() -> None:
    # The watchdog thread itself only got a third of its own polls in: the
    # host, not our loop, is what stopped scheduling.
    verdict = classify_freeze(
        service_ratio=0.33,
        cpu_fraction=0.0,
        starvation_service_ratio=0.5,
    )
    assert verdict == FREEZE_STARVED


def test_healthy_observer_with_frozen_loop_is_classified_as_a_block() -> None:
    # The watchdog thread kept its 1Hz schedule while the beacon went stale:
    # only the event loop stopped — a genuine synchronous block.
    verdict = classify_freeze(
        service_ratio=0.98,
        cpu_fraction=0.0,
        starvation_service_ratio=0.5,
    )
    assert verdict == FREEZE_BLOCKED


def test_starvation_verdict_vetoes_the_hard_restart() -> None:
    assert (
        may_hard_restart(
            verdict=FREEZE_STARVED, episode_count=9, restart_after_episodes=2
        )
        is False
    )


def test_first_episode_of_a_real_block_does_not_restart() -> None:
    assert (
        may_hard_restart(
            verdict=FREEZE_BLOCKED, episode_count=1, restart_after_episodes=2
        )
        is False
    )


def test_repeat_episode_of_a_real_block_restarts() -> None:
    assert (
        may_hard_restart(
            verdict=FREEZE_BLOCKED, episode_count=2, restart_after_episodes=2
        )
        is True
    )


# ---------------------------------------------------------------------------
# 2. The wired watchdog: notify stays sensitive, restart gets stricter
# ---------------------------------------------------------------------------


def test_starved_trip_writes_the_marker_so_the_issue_is_still_filed(
    tmp_path: Path,
) -> None:
    clock = _SteppingClock()
    exit_calls: list[int] = []
    wd = _watchdog(tmp_path, clock=clock, exit_calls=exit_calls)
    # One giant jump == the watchdog thread got a single poll in 150s.
    clock.advance(150.0)
    assert wd._check_once() is True
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None


def test_starved_trip_never_exits_even_with_hard_restart_armed(
    tmp_path: Path,
) -> None:
    clock = _SteppingClock()
    exit_calls: list[int] = []
    wd = _watchdog(tmp_path, clock=clock, exit_calls=exit_calls)
    clock.advance(150.0)
    wd._check_once()
    assert exit_calls == []


def test_starved_trip_records_its_verdict_in_the_marker(tmp_path: Path) -> None:
    clock = _SteppingClock()
    exit_calls: list[int] = []
    wd = _watchdog(tmp_path, clock=clock, exit_calls=exit_calls)
    clock.advance(150.0)
    wd._check_once()
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["verdict"] == FREEZE_STARVED


def test_first_block_episode_notifies_without_exiting(tmp_path: Path) -> None:
    clock = _SteppingClock()
    exit_calls: list[int] = []
    wd = _watchdog(tmp_path, clock=clock, exit_calls=exit_calls)
    _poll_through(wd, clock, 150.0)
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert exit_calls == []


def test_second_block_episode_exits_for_the_supervisor(tmp_path: Path) -> None:
    clock = _SteppingClock()
    exit_calls: list[int] = []
    wd = _watchdog(tmp_path, clock=clock, exit_calls=exit_calls)
    _poll_through(wd, clock, 150.0)
    wd._beacon.stamp()  # loop recovers: episode closes
    _poll_through(wd, clock, 5.0)
    _poll_through(wd, clock, 150.0)  # second, distinct freeze
    assert exit_calls == [EVENT_LOOP_STALL_EXIT_CODE]


# ---------------------------------------------------------------------------
# 3. The tally's bound — hypothesis-1's actual verdict, pinned
# ---------------------------------------------------------------------------


def test_event_log_cap_applies_after_the_since_filter(tmp_path: Path) -> None:
    """The on-loop tally walks at most ``max_events``, whatever the file size.

    Measured on the live 12.3 MB / 19,435-line factory log: 5000 events
    returned, 1.8 ms of tally. Were the cap applied BEFORE the ``since``
    filter (or dropped), the tally would grow with the file and the on-loop
    cost would be real.
    """
    from events import EventLog, EventType, HydraFlowEvent

    now = datetime.now(UTC)
    path = tmp_path / "events.jsonl"
    lines = [
        HydraFlowEvent(
            id=i,
            type=EventType.BACKGROUND_WORKER_STATUS,
            timestamp=(now - timedelta(seconds=60 - i * 0.001)).isoformat(),
            data={"worker": "w"},
        ).model_dump_json()
        for i in range(50)
    ]
    path.write_text("\n".join(lines) + "\n", encoding="utf-8")

    loaded = EventLog(path)._load_sync(now - timedelta(days=1), 10)
    assert len(loaded) == 10
