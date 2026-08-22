"""Thread-level event-loop freeze detector (#9552).

The per-cycle asyncio watchdog (#9455 / #9556, ``BaseBackgroundLoop.
_execute_cycle``) can only cancel a cycle blocked on an *await*. A
SYNCHRONOUS block inside ``_do_work`` — a CPU spin, blocking file I/O, a
non-async ``subprocess.run`` — freezes the entire event loop, so every
asyncio-scheduled watcher (the cycle watchdog, HealthMonitorLoop's
dead-man-switches, any pacemaker task) freezes with it. Detecting this
class requires an observer OUTSIDE the event loop.

Liveness layering — this module complements, and must not duplicate, its
siblings:

- asyncio cycle watchdog (#9556): bounds one cycle's await; runs IN the loop.
- THIS module: a daemon OS thread wall-clocks a 1s asyncio beacon the loop
  stamps; catches "process alive but event loop frozen solid". IN-process,
  out-of-loop.
- ``scripts/factory_liveness_watchdog.py`` (#10009): external cron/launchd
  check; catches whole-process death/hang from OUTSIDE the process.

On a stale beacon (older than ``event_loop_watchdog_stall_seconds``), once
per freeze episode, the thread:

1. dumps ALL thread stacks via ``faulthandler`` to a diagnostics file and
   stderr — the diagnostic gold: it names the exact blocking frame;
2. writes a stall marker consumed by ``HealthMonitorLoop.
   _check_event_loop_stall`` on the next healthy cycle (the thread cannot
   file GitHub issues itself — Ports are async and run on the very loop
   that froze), which files one ``hydraflow-find`` + ``loop-stalled`` issue;
3. only when the default-OFF ``event_loop_watchdog_hard_restart`` knob is
   enabled AND the freeze survives the two escalation gates below, hard-exits
   with ``EVENT_LOOP_STALL_EXIT_CODE`` so systemd/docker/launchd restarts the
   process (notify-default, restart-opt-in — the branch-GC /
   external-liveness-watchdog precedent).

Starvation vs. block (#11604). A wall-clock beacon cannot tell "the loop is
wedged" from "the HOST is oversubscribed and nothing got scheduled" — and
restarting a *starved* process makes a busy host busier. The trip therefore
classifies itself before touching the destructive path, from two signals the
watchdog already has:

- **Observer service ratio** — the watchdog thread's OWN poll cadence over the
  freeze window (polls actually taken ÷ polls the ``poll_seconds`` schedule
  called for). A wedged event loop does not stop a separate OS thread from
  waking on time, so a true block reads ~1.0; when the host starves the
  process, the observer loses its own schedule too and the ratio collapses.
  This is the existing observer self-reporting, not a meta-meta-watcher
  (ADR-0106 non-goal): no new thread, no new timer.
- **Process CPU fraction** — ``time.process_time()`` burned per wall second
  across the freeze. At/above :data:`SPIN_CPU_FRACTION` the process is
  demonstrably burning its own CPU, which positively confirms an in-process
  spin. It cannot *refute* a block (a blocking syscall burns none), so it only
  ever upgrades a verdict, never downgrades one.

The NOTIFY half (dump + marker + issue) stays sensitive: it fires on the first
episode whatever the verdict, so a starved host still surfaces. Only the
destructive half gets stricter — see :func:`may_hard_restart`.
"""

from __future__ import annotations

import asyncio
import contextlib
import faulthandler
import json
import logging
import os
import sys
import threading
import time
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from collections.abc import Callable
    from pathlib import Path

    from config import HydraFlowConfig

logger = logging.getLogger("hydraflow.event_loop_watchdog")

#: ``EX_TEMPFAIL`` — "transient failure, retry me". Distinct from generic
#: crash exit codes so supervisors/logs can attribute a restart to a frozen
#: event loop specifically.
EVENT_LOOP_STALL_EXIT_CODE = 75

#: How often the asyncio beacon task stamps the heartbeat. Deliberately a
#: constant, not a knob: the operator-facing dial is the stall threshold; a
#: 1s beacon makes the threshold read directly as "seconds of frozen loop".
BEACON_INTERVAL_SECONDS = 1.0

#: Default watchdog-thread poll cadence. Also the bound on how long
#: :meth:`EventLoopWatchdog.stop` can block joining the thread.
DEFAULT_POLL_SECONDS = 1.0

#: Process CPU seconds burned per wall second above which a freeze is
#: positively OUR OWN spin rather than the host's fault. Deliberately a
#: constant, not a knob: it is a statement about physics (half a core is more
#: than a starved process ever gets), and the operator-facing dials are the
#: two below it in the decision. A blocking syscall burns ~0 here, so this
#: signal can only ever *upgrade* a verdict toward "restart me".
SPIN_CPU_FRACTION = 0.5

#: The event loop stopped scheduling while the watchdog thread kept its own
#: cadence and the process burned little CPU — a blocking syscall / non-async
#: ``subprocess.run`` / blocking file I/O on the loop thread.
FREEZE_BLOCKED = "blocked"

#: As above, but the process was demonstrably burning its own CPU: an
#: in-process spin. The strongest "this is our bug, restart me" signal.
FREEZE_BLOCKED_SPIN = "blocked_spin"

#: The watchdog thread lost its OWN schedule alongside the loop — the host
#: was oversubscribed, not the loop wedged. Restarting here makes a busy host
#: busier and destroys in-flight work for nothing (#11604).
FREEZE_STARVED = "starved"

_MARKER_FILENAME = "event_loop_stall.json"

# Process-wide single-flight slot: in multi-repo mode every orchestrator
# calls start(), but all of them share ONE event loop — a second beacon +
# thread would just duplicate detection (and multiply dumps). First start
# wins; the rest become passive no-ops. One-element-list slot instead of a
# rebindable global (the trace_collector._ACTIVE_CONFIG_SLOT pattern).
_ACTIVE_LOCK = threading.Lock()
_ACTIVE_SLOT: list[EventLoopWatchdog | None] = [None]


def event_loop_stall_marker_path(config: HydraFlowConfig) -> Path:
    """Canonical marker location — shared by the watchdog (writer) and
    ``HealthMonitorLoop._check_event_loop_stall`` (reader/consumer)."""
    return config.diagnostics_dir / _MARKER_FILENAME


def read_stall_marker(path: Path) -> dict[str, Any] | None:
    """Return the stall-marker payload, or ``None`` if absent/corrupt."""
    if not path.exists():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        logger.warning(
            "Could not read event-loop stall marker %s — treating as absent", path
        )
        return None
    return data if isinstance(data, dict) else None


def write_stall_marker(path: Path, payload: dict[str, Any]) -> None:
    """Atomically persist *payload* (write-then-``os.replace``)."""
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name + ".tmp")
    tmp.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    os.replace(tmp, path)


def clear_stall_marker(path: Path) -> None:
    """Consume the marker. Missing file is fine (already consumed)."""
    path.unlink(missing_ok=True)


@dataclass(frozen=True)
class HostLoad:
    """What the watchdog thread observed about ITSELF across a freeze window.

    ``service_ratio`` is polls actually taken ÷ polls the ``poll_seconds``
    schedule called for over ``elapsed`` wall seconds (clamped to 1.0);
    ``cpu_fraction`` is process CPU seconds burned per wall second. Both are
    derived purely from the clocks the thread already reads.
    """

    service_ratio: float
    cpu_fraction: float
    polls: int
    elapsed: float


def classify_freeze(
    *,
    service_ratio: float,
    cpu_fraction: float,
    starvation_service_ratio: float,
    spin_cpu_fraction: float = SPIN_CPU_FRACTION,
) -> str:
    """Name the freeze: :data:`FREEZE_BLOCKED_SPIN`, ``_BLOCKED`` or ``_STARVED``.

    Order matters. A process burning half a core or more is *demonstrably*
    doing its own work, so that check runs first and wins even against a poor
    service ratio (a spin contends for the GIL and can itself delay the
    observer). Otherwise a collapsed observer cadence means the host stopped
    scheduling us — starvation. Everything else is a genuine block.
    """
    if cpu_fraction >= spin_cpu_fraction:
        return FREEZE_BLOCKED_SPIN
    if service_ratio < starvation_service_ratio:
        return FREEZE_STARVED
    return FREEZE_BLOCKED


def may_hard_restart(
    *, verdict: str, episode_count: int, restart_after_episodes: int
) -> bool:
    """Whether the DESTRUCTIVE path may run for this trip.

    Two gates, both required (#11604):

    1. the freeze must not be host starvation — killing a starved process adds
       a fresh startup's worth of load to the host that starved it;
    2. it must be the ``restart_after_episodes``-th accumulated episode.
       ``episode_count`` is the marker's existing accumulator, which resets
       only when ``HealthMonitorLoop`` gets a healthy cycle and consumes the
       marker. So "recovered in place well enough to file the issue" resets the
       count, while "froze, recovered, froze again with no useful work in
       between" climbs it — exactly the state where in-place recovery has
       stopped working and a supervisor restart is the right answer.

    Note this gates only ``os._exit``. The dump, the marker and the filed
    ``loop-stalled`` issue are unconditional on the first episode.
    """
    if verdict == FREEZE_STARVED:
        return False
    return episode_count >= restart_after_episodes


class EventLoopBeacon:
    """Monotonic liveness stamp bridging the event loop and the thread.

    The loop thread calls :meth:`stamp` (from the beacon task); the watchdog
    thread calls :meth:`age`. A float attribute write/read is atomic under
    the GIL, so no lock is needed. ``clock`` is injectable so tests never
    monkeypatch global ``time.monotonic`` (the documented xdist/coverage
    clock-patch flake trap).
    """

    def __init__(self, *, clock: Callable[[], float] = time.monotonic) -> None:
        self._clock = clock
        self._last: float = clock()

    def stamp(self) -> None:
        """Record 'the event loop was scheduling tasks at this instant'."""
        self._last = self._clock()

    def age(self) -> float:
        """Seconds since the loop last proved liveness."""
        return self._clock() - self._last


class EventLoopWatchdog:
    """Daemon-thread observer for a synchronously-frozen asyncio event loop.

    Built by :func:`build_event_loop_watchdog` in production (which threads
    the config knobs through as callables so System-tab edits apply live);
    tests construct it directly with tiny thresholds and an injected
    ``exit_fn`` so nothing ever actually kills the test runner.
    """

    def __init__(
        self,
        *,
        stall_seconds_cb: Callable[[], float],
        hard_restart_cb: Callable[[], bool],
        diagnostics_dir: Path,
        restart_after_episodes_cb: Callable[[], int] | None = None,
        starvation_service_ratio_cb: Callable[[], float] | None = None,
        beacon_interval: float = BEACON_INTERVAL_SECONDS,
        poll_seconds: float = DEFAULT_POLL_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        cpu_clock: Callable[[], float] = time.process_time,
        exit_fn: Callable[[int], None] | None = None,
        dump_fn: Callable[[Path], None] | None = None,
    ) -> None:
        self._stall_seconds_cb = stall_seconds_cb
        self._hard_restart_cb = hard_restart_cb
        # Defaults mirror the config defaults so a directly-constructed
        # watchdog (tests, embedders) gets the conservative policy too.
        self._restart_after_episodes_cb = restart_after_episodes_cb or (lambda: 2)
        self._starvation_service_ratio_cb = starvation_service_ratio_cb or (lambda: 0.5)
        self._diagnostics_dir = diagnostics_dir
        self._marker_path = diagnostics_dir / _MARKER_FILENAME
        self._beacon_interval = beacon_interval
        self._poll_seconds = poll_seconds
        self._clock = clock
        self._cpu_clock = cpu_clock
        self._beacon = EventLoopBeacon(clock=clock)
        # Observer self-cadence baseline (#11604), re-anchored on every poll
        # that sees a fresh beacon. Together these answer "did the watchdog
        # thread keep its OWN schedule while the loop was frozen?".
        self._fresh_at: float = clock()
        self._cpu_at_fresh: float = cpu_clock()
        self._polls_since_fresh = 0
        # os._exit, not sys.exit: a clean shutdown needs the (frozen) event
        # loop to cooperate, which is exactly what it cannot do. Injectable
        # so tests record the call instead of dying.
        self._exit_fn: Callable[[int], None] = exit_fn or os._exit
        self._dump_fn: Callable[[Path], None] = dump_fn or self._default_dump
        self._thread_stop = threading.Event()
        self._thread: threading.Thread | None = None
        self._beacon_task: asyncio.Task[None] | None = None
        # Debounce: one dump + one marker per freeze episode, not one per
        # poll tick. Cleared when the beacon goes fresh again (recovery).
        self._episode_active = False
        self._check_error_logged = False
        self._owns_slot = False

    # -- lifecycle ---------------------------------------------------------

    def start(self) -> bool:
        """Arm the watchdog: beacon task on the running loop + daemon thread.

        Must be called from a running event loop (the one to be watched).
        Returns ``False`` (passive no-op) when another watchdog already owns
        the process slot — multi-repo orchestrators share one loop and need
        only one observer.
        """
        with _ACTIVE_LOCK:
            active = _ACTIVE_SLOT[0]
            if active is not None and active is not self:
                logger.debug(
                    "Event-loop watchdog already active in this process — "
                    "this instance stays passive"
                )
                return False
            _ACTIVE_SLOT[0] = self
        self._owns_slot = True
        self._thread_stop.clear()
        self._beacon.stamp()
        self._mark_observer_fresh(self._clock())
        self._beacon_task = asyncio.get_running_loop().create_task(
            self._beacon_loop(), name="hydraflow-event-loop-beacon"
        )
        self._thread = threading.Thread(
            target=self._thread_main,
            name="hydraflow-event-loop-watchdog",
            daemon=True,
        )
        self._thread.start()
        logger.info(
            "Event-loop freeze detector armed (stall threshold %.0fs, hard_restart=%s)",
            float(self._stall_seconds_cb()),
            bool(self._hard_restart_cb()),
        )
        return True

    def stop(self) -> None:
        """Disarm promptly: stop the thread (bounded join) + cancel the beacon.

        Safe to call multiple times and on a passive (never-started) instance.
        The thread is a daemon either way, so even a missed stop can never
        wedge interpreter shutdown or test teardown.
        """
        self._thread_stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self._poll_seconds + 1.0)
            self._thread = None
        if self._beacon_task is not None:
            self._beacon_task.cancel()
            self._beacon_task = None
        if self._owns_slot:
            with _ACTIVE_LOCK:
                if _ACTIVE_SLOT[0] is self:
                    _ACTIVE_SLOT[0] = None
            self._owns_slot = False

    # -- event-loop side ---------------------------------------------------

    async def _beacon_loop(self) -> None:
        """Stamp the beacon every ``beacon_interval`` seconds.

        Trivially cheap (one monotonic read + float store per second). While
        the loop is synchronously blocked this coroutine is simply never
        scheduled — which is precisely the signal the thread reads.
        """
        while not self._thread_stop.is_set():
            self._beacon.stamp()
            await asyncio.sleep(self._beacon_interval)

    # -- watchdog-thread side ----------------------------------------------

    def _thread_main(self) -> None:
        while not self._thread_stop.wait(self._poll_seconds):
            try:
                self._check_once()
            except Exception:
                # Watchdog must outlive its own bugs — log once, keep polling.
                if not self._check_error_logged:
                    self._check_error_logged = True
                    logger.exception(
                        "Event-loop watchdog check failed — logged once, "
                        "the thread keeps polling"
                    )

    def _check_once(self) -> bool:
        """One staleness check. Returns True only when a trip fired.

        Episode semantics: the first poll past the threshold trips (dump +
        marker + optional hard restart); subsequent polls of the SAME frozen
        episode are silent; a fresh beacon closes the episode so a later
        freeze trips again.
        """
        now = self._clock()
        self._polls_since_fresh += 1
        age = self._beacon.age()
        threshold = float(self._stall_seconds_cb())
        if age < threshold:
            self._mark_observer_fresh(now)
            if self._episode_active:
                self._episode_active = False
                logger.warning(
                    "Event loop recovered — beacon fresh again (age %.1fs) "
                    "after a synchronous stall episode",
                    age,
                )
            return False
        if self._episode_active:
            return False
        self._episode_active = True
        self._trip(age, threshold, self._observe_host(now))
        return True

    def _mark_observer_fresh(self, now: float) -> None:
        """Re-anchor the observer self-cadence baseline (#11604)."""
        self._fresh_at = now
        self._cpu_at_fresh = self._cpu_clock()
        self._polls_since_fresh = 0

    def _observe_host(self, now: float) -> HostLoad:
        """Measure the watchdog thread's own service since the last fresh poll.

        Both ratios are clamped and zero-guarded: a degenerate reading must
        never be what decides whether the process dies.
        """
        elapsed = max(now - self._fresh_at, 0.0)
        cpu_delta = max(self._cpu_clock() - self._cpu_at_fresh, 0.0)
        expected_polls = elapsed / self._poll_seconds if self._poll_seconds > 0 else 0.0
        service_ratio = (
            1.0
            if expected_polls <= 0.0
            else min(self._polls_since_fresh / expected_polls, 1.0)
        )
        cpu_fraction = 0.0 if elapsed <= 0.0 else cpu_delta / elapsed
        return HostLoad(
            service_ratio=service_ratio,
            cpu_fraction=cpu_fraction,
            polls=self._polls_since_fresh,
            elapsed=elapsed,
        )

    def _trip(self, age: float, threshold: float, load: HostLoad) -> None:
        detected_at = datetime.now(UTC)
        dump_path = self._diagnostics_dir / (
            f"event_loop_stall_{detected_at.strftime('%Y%m%dT%H%M%SZ')}.txt"
        )
        verdict = classify_freeze(
            service_ratio=load.service_ratio,
            cpu_fraction=load.cpu_fraction,
            starvation_service_ratio=float(self._starvation_service_ratio_cb()),
        )
        logger.critical(
            "Event loop FROZEN: liveness beacon stale for %.1fs "
            "(threshold %.0fs, verdict=%s, observer service %.2f, process CPU "
            "%.2f/wall-s) — dumping all thread stacks to %s",
            age,
            threshold,
            verdict,
            load.service_ratio,
            load.cpu_fraction,
            dump_path,
        )
        try:
            self._dump_fn(dump_path)
        except Exception:
            # Diagnostics must not kill the escalation that follows.
            logger.exception("faulthandler stack dump failed")
        prior = read_stall_marker(self._marker_path)
        # Episodes that froze-and-recovered before the health monitor consumed
        # the marker accumulate here instead of being lost — and, since
        # #11604, gate the destructive path.
        episode_count = (prior.get("episode_count", 0) if prior else 0) + 1
        restart_after = int(self._restart_after_episodes_cb())
        armed = bool(self._hard_restart_cb())
        allowed = may_hard_restart(
            verdict=verdict,
            episode_count=episode_count,
            restart_after_episodes=restart_after,
        )
        if not armed:
            decision = "disabled"
        elif allowed:
            decision = "restarting"
        elif verdict == FREEZE_STARVED:
            decision = "suppressed_starvation"
        else:
            decision = "suppressed_episodes"
        payload: dict[str, Any] = {
            "detected_at": detected_at.isoformat(),
            "stalled_for_seconds": round(age, 1),
            "threshold_seconds": threshold,
            "pid": os.getpid(),
            "dump_path": str(dump_path),
            "hard_restart": armed,
            "episode_count": episode_count,
            "verdict": verdict,
            "restart_decision": decision,
            "restart_after_episodes": restart_after,
            "observer_service_ratio": round(load.service_ratio, 3),
            "process_cpu_fraction": round(load.cpu_fraction, 3),
            # The raw counts behind the ratio, so an operator can sanity-check
            # the verdict instead of taking it on faith.
            "observer_polls": load.polls,
            "observer_window_seconds": round(load.elapsed, 1),
        }
        try:
            write_stall_marker(self._marker_path, payload)
        except Exception:
            # The marker is a best-effort breadcrumb, never fatal.
            logger.exception("Could not write event-loop stall marker")
        if not armed:
            return
        if not allowed:
            logger.critical(
                "event_loop_watchdog_hard_restart is enabled but the restart "
                "is SUPPRESSED (%s): verdict=%s, episode %d of %d required. "
                "The stall marker is written and the health monitor will file "
                "the issue — no process exit.",
                decision,
                verdict,
                episode_count,
                restart_after,
            )
            return
        logger.critical(
            "event_loop_watchdog_hard_restart is enabled and this freeze is "
            "attributable to the process (verdict=%s, episode %d of %d) — "
            "exiting with code %d so the process supervisor restarts a live "
            "instance",
            verdict,
            episode_count,
            restart_after,
            EVENT_LOOP_STALL_EXIT_CODE,
        )
        self._exit_fn(EVENT_LOOP_STALL_EXIT_CODE)

    def _default_dump(self, path: Path) -> None:
        """All-thread stack dump to *path* and (best-effort) stderr.

        The frozen loop thread's top Python frame in this dump IS the
        offending synchronous call site — the one artifact that turns "the
        factory hung" into a one-line fix.
        """
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", encoding="utf-8") as fh:
            faulthandler.dump_traceback(file=fh, all_threads=True)
        with contextlib.suppress(Exception):
            faulthandler.dump_traceback(file=sys.stderr, all_threads=True)


def build_event_loop_watchdog(
    config: HydraFlowConfig, *, force: bool = False
) -> EventLoopWatchdog | None:
    """Config-wired watchdog for orchestrator startup, or ``None``.

    Returns ``None`` when the ``event_loop_watchdog_enabled`` knob is off, or
    under pytest (mirroring ``server._init_sentry``: orchestrators spun up by
    tests/MockWorld scenarios must not grow real observer threads).
    ``force=True`` bypasses the pytest guard so the watchdog's own tests can
    exercise the builder wiring.

    The threshold/hard-restart knobs are threaded through as callables that
    re-read the live config object each poll, so System-tab edits apply
    without a restart (the control route mutates the config in place).
    """
    if not config.event_loop_watchdog_enabled:
        return None
    if not force and (os.environ.get("PYTEST_CURRENT_TEST") or "pytest" in sys.modules):
        return None
    return EventLoopWatchdog(
        stall_seconds_cb=lambda: config.event_loop_watchdog_stall_seconds,
        hard_restart_cb=lambda: config.event_loop_watchdog_hard_restart,
        restart_after_episodes_cb=(
            lambda: config.event_loop_watchdog_restart_after_episodes
        ),
        starvation_service_ratio_cb=(
            lambda: config.event_loop_watchdog_starvation_service_ratio
        ),
        diagnostics_dir=config.diagnostics_dir,
    )
