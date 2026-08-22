"""Unit + behavioral tests for the thread-level event-loop freeze detector.

Issue #9552. The deterministic core (`_check_once`) is driven with an
injected stepping clock — no sleeping, no global ``time.monotonic``
monkeypatching. The behavioral tests run a REAL event loop in a child
thread, block it synchronously with ``time.sleep``, and assert the watchdog
thread observes the freeze from outside — the exact class the asyncio cycle
watchdog cannot see. ``exit_fn`` is always injected; ``os._exit`` never runs.
"""

from __future__ import annotations

import asyncio
import threading
import time
from pathlib import Path

from config import HydraFlowConfig
from event_loop_watchdog import (
    EVENT_LOOP_STALL_EXIT_CODE,
    FREEZE_BLOCKED,
    FREEZE_BLOCKED_SPIN,
    FREEZE_STARVED,
    EventLoopBeacon,
    EventLoopWatchdog,
    build_event_loop_watchdog,
    classify_freeze,
    clear_stall_marker,
    event_loop_stall_marker_path,
    read_stall_marker,
    write_stall_marker,
)


class SteppingClock:
    """Deterministic monotonic clock — advanced explicitly by the test."""

    def __init__(self) -> None:
        self.now = 1000.0

    def __call__(self) -> float:
        return self.now

    def advance(self, seconds: float) -> None:
        self.now += seconds


def _make_watchdog(
    tmp_path: Path,
    *,
    stall: float = 100.0,
    hard_restart: bool = False,
    restart_after: int = 2,
    starvation_ratio: float = 0.5,
    clock: SteppingClock | None = None,
    poll: float = 0.05,
    beacon_interval: float = 0.05,
    exit_calls: list[int] | None = None,
    dump_calls: list[Path] | None = None,
) -> EventLoopWatchdog:
    return EventLoopWatchdog(
        stall_seconds_cb=lambda: stall,
        hard_restart_cb=lambda: hard_restart,
        restart_after_episodes_cb=lambda: restart_after,
        starvation_service_ratio_cb=lambda: starvation_ratio,
        diagnostics_dir=tmp_path / "diagnostics",
        beacon_interval=beacon_interval,
        poll_seconds=poll,
        clock=clock if clock is not None else time.monotonic,
        cpu_clock=lambda: 0.0,
        exit_fn=exit_calls.append if exit_calls is not None else (lambda _c: None),
        dump_fn=dump_calls.append if dump_calls is not None else None,
    )


def _poll_through(
    wd: EventLoopWatchdog, clock: SteppingClock, seconds: float, *, poll: float = 0.05
) -> None:
    """Advance *clock* in poll-sized steps, checking once per step.

    Faithful to the daemon thread's real cadence. A single giant clock jump
    simulates a watchdog thread that itself stopped running — which since
    #11604 is the host-starvation signature that vetoes the restart, so any
    test of the BLOCK path must step the clock the way the thread really
    walks it.
    """
    for _ in range(int(round(seconds / poll))):
        clock.advance(poll)
        wd._check_once()


# ---------------------------------------------------------------------------
# Beacon staleness math
# ---------------------------------------------------------------------------


def test_beacon_age_grows_with_clock_and_resets_on_stamp() -> None:
    clock = SteppingClock()
    beacon = EventLoopBeacon(clock=clock)
    assert beacon.age() == 0.0
    clock.advance(42.0)
    assert beacon.age() == 42.0
    beacon.stamp()
    assert beacon.age() == 0.0


# ---------------------------------------------------------------------------
# _check_once: detection core (deterministic, no threads, no sleeping)
# ---------------------------------------------------------------------------


def test_fresh_beacon_does_not_trip(tmp_path: Path) -> None:
    clock = SteppingClock()
    exit_calls: list[int] = []
    dump_calls: list[Path] = []
    wd = _make_watchdog(
        tmp_path, stall=100.0, clock=clock, exit_calls=exit_calls, dump_calls=dump_calls
    )
    clock.advance(99.0)
    assert wd._check_once() is False
    assert dump_calls == []
    assert exit_calls == []
    assert read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json") is None


def test_stale_beacon_trips_with_dump_and_marker_but_no_exit_by_default(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    exit_calls: list[int] = []
    dump_calls: list[Path] = []
    wd = _make_watchdog(
        tmp_path, stall=100.0, clock=clock, exit_calls=exit_calls, dump_calls=dump_calls
    )
    clock.advance(150.0)
    assert wd._check_once() is True
    assert len(dump_calls) == 1
    assert dump_calls[0].name.startswith("event_loop_stall_")
    # Recovery is OPT-IN and defaults OFF: detection must never exit.
    assert exit_calls == []
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["stalled_for_seconds"] == 150.0
    assert marker["threshold_seconds"] == 100.0
    assert marker["episode_count"] == 1
    assert marker["hard_restart"] is False
    assert marker["dump_path"] == str(dump_calls[0])


def test_one_trip_per_freeze_episode_not_per_poll(tmp_path: Path) -> None:
    clock = SteppingClock()
    dump_calls: list[Path] = []
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock, dump_calls=dump_calls)
    clock.advance(150.0)
    assert wd._check_once() is True
    clock.advance(50.0)  # still frozen — same episode
    assert wd._check_once() is False
    clock.advance(50.0)
    assert wd._check_once() is False
    assert len(dump_calls) == 1


def test_recovery_closes_episode_and_a_second_freeze_trips_again(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    dump_calls: list[Path] = []
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock, dump_calls=dump_calls)
    clock.advance(150.0)
    assert wd._check_once() is True
    # Loop recovers: beacon stamped fresh again.
    wd._beacon.stamp()
    assert wd._check_once() is False
    # Second, distinct freeze episode.
    clock.advance(200.0)
    assert wd._check_once() is True
    assert len(dump_calls) == 2
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    # Unconsumed prior episode accumulates instead of being lost.
    assert marker["episode_count"] == 2


def test_hard_restart_knob_invokes_exit_fn_once_with_stall_code(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    exit_calls: list[int] = []
    dump_calls: list[Path] = []
    wd = _make_watchdog(
        tmp_path,
        stall=100.0,
        hard_restart=True,
        restart_after=1,  # #11604 gate opened: pin the exit path itself here
        clock=clock,
        exit_calls=exit_calls,
        dump_calls=dump_calls,
    )
    _poll_through(wd, clock, 150.0)
    assert exit_calls == [EVENT_LOOP_STALL_EXIT_CODE]


def test_hard_restart_writes_dump_and_marker_before_exiting(tmp_path: Path) -> None:
    clock = SteppingClock()
    dump_calls: list[Path] = []
    wd = _make_watchdog(
        tmp_path,
        stall=100.0,
        hard_restart=True,
        restart_after=1,
        clock=clock,
        dump_calls=dump_calls,
    )
    _poll_through(wd, clock, 150.0)
    # Dump + marker land BEFORE the exit so diagnostics survive the restart.
    assert len(dump_calls) == 1
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["hard_restart"] is True


def test_default_dump_writes_all_thread_stacks(tmp_path: Path) -> None:
    wd = _make_watchdog(tmp_path)
    dump_path = tmp_path / "diagnostics" / "dump.txt"
    wd._default_dump(dump_path)
    text = dump_path.read_text(encoding="utf-8")
    # faulthandler names threads and the current test frame.
    assert "Current thread" in text or "Thread" in text
    assert "test_default_dump_writes_all_thread_stacks" in text


# ---------------------------------------------------------------------------
# Freeze classification (#11604): starvation vs block vs spin
# ---------------------------------------------------------------------------


def test_cpu_burn_classifies_as_an_in_process_spin() -> None:
    # Burning most of a core proves the work is ours, whatever the host is
    # doing — this verdict outranks a poor observer ratio.
    verdict = classify_freeze(
        service_ratio=0.2,
        cpu_fraction=0.9,
        starvation_service_ratio=0.5,
    )
    assert verdict == FREEZE_BLOCKED_SPIN


def test_starvation_veto_is_disabled_by_a_zero_ratio() -> None:
    # The documented escape hatch: ratio 0.0 means "never blame the host".
    verdict = classify_freeze(
        service_ratio=0.0,
        cpu_fraction=0.0,
        starvation_service_ratio=0.0,
    )
    assert verdict == FREEZE_BLOCKED


def test_observer_ratio_reads_healthy_when_the_thread_keeps_its_cadence(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock, poll=1.0)
    _poll_through(wd, clock, 60.0, poll=1.0)
    assert wd._observe_host(clock()).service_ratio == 1.0


def test_observer_ratio_collapses_when_the_thread_loses_its_cadence(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock, poll=1.0)
    # Ten polls where sixty were due: the host gave the observer a sixth of
    # its own schedule.
    _poll_through(wd, clock, 10.0, poll=1.0)
    clock.advance(50.0)
    assert wd._observe_host(clock()).service_ratio < 0.5


def test_starved_trip_marker_names_the_suppression_reason(tmp_path: Path) -> None:
    clock = SteppingClock()
    exit_calls: list[int] = []
    wd = _make_watchdog(
        tmp_path, stall=100.0, hard_restart=True, clock=clock, exit_calls=exit_calls
    )
    clock.advance(150.0)  # one poll where 3000 were due — starvation
    wd._check_once()
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["restart_decision"] == "suppressed_starvation"


def test_notify_only_config_reports_a_disabled_restart_decision(
    tmp_path: Path,
) -> None:
    clock = SteppingClock()
    wd = _make_watchdog(tmp_path, stall=100.0, hard_restart=False, clock=clock)
    _poll_through(wd, clock, 150.0)
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["restart_decision"] == "disabled"


def test_block_verdict_is_recorded_for_a_healthy_observer(tmp_path: Path) -> None:
    clock = SteppingClock()
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock)
    _poll_through(wd, clock, 150.0)
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["verdict"] == FREEZE_BLOCKED


def test_starvation_verdict_is_recorded_for_a_starved_observer(tmp_path: Path) -> None:
    clock = SteppingClock()
    wd = _make_watchdog(tmp_path, stall=100.0, clock=clock)
    clock.advance(150.0)
    wd._check_once()
    marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
    assert marker is not None
    assert marker["verdict"] == FREEZE_STARVED


# ---------------------------------------------------------------------------
# Marker helpers
# ---------------------------------------------------------------------------


def test_marker_roundtrip_and_clear(tmp_path: Path) -> None:
    path = tmp_path / "diagnostics" / "event_loop_stall.json"
    assert read_stall_marker(path) is None
    write_stall_marker(path, {"episode_count": 3})
    assert read_stall_marker(path) == {"episode_count": 3}
    clear_stall_marker(path)
    assert read_stall_marker(path) is None
    clear_stall_marker(path)  # idempotent


def test_corrupt_marker_reads_as_absent(tmp_path: Path) -> None:
    path = tmp_path / "event_loop_stall.json"
    path.write_text("{not json", encoding="utf-8")
    assert read_stall_marker(path) is None


# ---------------------------------------------------------------------------
# Lifecycle: thread start/stop + process-wide single-flight slot
# ---------------------------------------------------------------------------


async def test_stop_terminates_thread_promptly(tmp_path: Path) -> None:
    wd = _make_watchdog(tmp_path, poll=0.05)
    try:
        assert wd.start() is True
        thread = wd._thread
        assert thread is not None
        assert thread.is_alive()
        assert thread.daemon is True  # can never wedge interpreter shutdown
    finally:
        wd.stop()
    assert wd._thread is None
    assert not thread.is_alive()
    # Idempotent.
    wd.stop()


async def test_single_flight_one_watchdog_per_process(tmp_path: Path) -> None:
    wd1 = _make_watchdog(tmp_path / "a")
    wd2 = _make_watchdog(tmp_path / "b")
    try:
        assert wd1.start() is True
        # Second orchestrator on the same process/loop: passive no-op.
        assert wd2.start() is False
        assert wd2._thread is None
        # A passive instance's stop must NOT release the owner's slot.
        wd2.stop()
        wd3 = _make_watchdog(tmp_path / "c")
        assert wd3.start() is False
        wd3.stop()
    finally:
        wd1.stop()
    wd4 = _make_watchdog(tmp_path / "d")
    try:
        assert wd4.start() is True
    finally:
        wd4.stop()


# ---------------------------------------------------------------------------
# Behavioral: a REAL event loop, synchronously frozen, in a child thread
# ---------------------------------------------------------------------------


def test_detects_synchronously_frozen_event_loop_and_invokes_recovery(
    tmp_path: Path,
) -> None:
    """The headline #9552 scenario.

    A real event loop runs in a CHILD thread; ``time.sleep`` on that thread
    freezes it synchronously — the state no asyncio-level watchdog can see.
    The watchdog thread must detect the stale beacon, write the faulthandler
    dump naming the blocking frame, and (hard-restart knob ON) invoke the
    injected recovery callable. Nothing here goes near ``os._exit``/killpg.

    The two #11604 escalation gates are opened here on purpose. This test's
    job is the end-to-end freeze→dump→exit path on a REAL loop; the gates are
    decided by pure functions covered deterministically in
    ``tests/regressions/test_issue_11604.py``. Leaving the starvation veto
    armed would make the assertion depend on how loaded the CI host is —
    exactly the wall-clock sensitivity the veto exists to handle.
    """
    exit_calls: list[int] = []
    wd = EventLoopWatchdog(
        stall_seconds_cb=lambda: 0.5,
        hard_restart_cb=lambda: True,
        restart_after_episodes_cb=lambda: 1,
        starvation_service_ratio_cb=lambda: 0.0,
        diagnostics_dir=tmp_path / "diagnostics",
        beacon_interval=0.05,
        poll_seconds=0.05,
        exit_fn=exit_calls.append,
    )

    async def frozen_scenario() -> None:
        wd.start()
        await asyncio.sleep(0.2)  # beacon proves liveness while the loop pumps
        time.sleep(1.2)  # SYNCHRONOUS block on the loop thread — the freeze
        await asyncio.sleep(0.1)

    thread = threading.Thread(
        target=lambda: asyncio.run(frozen_scenario()), daemon=True
    )
    try:
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert exit_calls == [EVENT_LOOP_STALL_EXIT_CODE]
        dumps = sorted((tmp_path / "diagnostics").glob("event_loop_stall_*.txt"))
        assert dumps, "a trip must write a faulthandler dump"
        dump_text = dumps[0].read_text(encoding="utf-8")
        # The diagnostic gold: the frozen loop thread's top Python frame in
        # the dump names the synchronous call site.
        assert "frozen_scenario" in dump_text
        marker = read_stall_marker(tmp_path / "diagnostics" / "event_loop_stall.json")
        assert marker is not None
        assert marker["episode_count"] == 1
    finally:
        wd.stop()


def test_healthy_pumping_loop_never_trips(tmp_path: Path) -> None:
    """No false positives: a loop that keeps scheduling never trips."""
    exit_calls: list[int] = []
    dump_calls: list[Path] = []
    wd = EventLoopWatchdog(
        stall_seconds_cb=lambda: 5.0,
        hard_restart_cb=lambda: True,
        diagnostics_dir=tmp_path / "diagnostics",
        beacon_interval=0.05,
        poll_seconds=0.05,
        exit_fn=exit_calls.append,
        dump_fn=dump_calls.append,
    )

    async def healthy_scenario() -> None:
        wd.start()
        for _ in range(10):
            await asyncio.sleep(0.05)

    thread = threading.Thread(
        target=lambda: asyncio.run(healthy_scenario()), daemon=True
    )
    try:
        thread.start()
        thread.join(timeout=30)
        assert not thread.is_alive()
        assert exit_calls == []
        assert dump_calls == []
    finally:
        wd.stop()


# ---------------------------------------------------------------------------
# Builder wiring
# ---------------------------------------------------------------------------


def test_builder_returns_none_when_disabled(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(data_root=tmp_path, event_loop_watchdog_enabled=False)
    assert build_event_loop_watchdog(cfg, force=True) is None


def test_builder_returns_none_under_pytest_without_force(tmp_path: Path) -> None:
    # We ARE under pytest right now — the guard must keep orchestrators spun
    # up by tests/MockWorld scenarios from growing real observer threads.
    cfg = HydraFlowConfig(data_root=tmp_path)
    assert cfg.event_loop_watchdog_enabled is True
    assert build_event_loop_watchdog(cfg) is None


def test_builder_wires_live_config_callbacks(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        event_loop_watchdog_stall_seconds=300,
        event_loop_watchdog_hard_restart=True,
    )
    wd = build_event_loop_watchdog(cfg, force=True)
    assert wd is not None
    assert wd._stall_seconds_cb() == 300
    assert wd._hard_restart_cb() is True
    assert wd._diagnostics_dir == cfg.diagnostics_dir
    assert event_loop_stall_marker_path(cfg) == (
        cfg.diagnostics_dir / "event_loop_stall.json"
    )
    # LIVE knobs: the control route mutates the config object in place
    # (object.__setattr__) and the thread re-reads via these callables.
    object.__setattr__(cfg, "event_loop_watchdog_stall_seconds", 999)
    object.__setattr__(cfg, "event_loop_watchdog_hard_restart", False)
    assert wd._stall_seconds_cb() == 999
    assert wd._hard_restart_cb() is False


def test_builder_wires_the_escalation_gate_callbacks(tmp_path: Path) -> None:
    cfg = HydraFlowConfig(
        data_root=tmp_path,
        event_loop_watchdog_restart_after_episodes=3,
        event_loop_watchdog_starvation_service_ratio=0.25,
    )
    wd = build_event_loop_watchdog(cfg, force=True)
    assert wd is not None
    assert wd._restart_after_episodes_cb() == 3
    assert wd._starvation_service_ratio_cb() == 0.25
