# ADR-0106: Thread-level event-loop freeze detector

**Status:** Accepted
**Date:** 2026-07-20
**Enforcement:** enforced
**Enforced by:**
pytest:tests/regressions/test_issue_9552.py
pytest:tests/regressions/test_issue_11604.py

## Context

HydraFlow's liveness story had three layers with a hole in the middle. The per-cycle asyncio watchdog (#9455 / #9556, `src/base_background_loop.py`) bounds every `_do_work()` cycle — but it is itself an `await asyncio.wait(...)`, so it can only cancel a cycle that is blocked *on an await*. The external liveness watchdog (#10009, `scripts/factory_liveness_watchdog.py`) runs outside the process via cron/launchd and catches whole-process death or a wedged `/healthz`. The hole (#9552): a **synchronous** block inside any loop's `_do_work` — a CPU spin, blocking file I/O, a non-async `subprocess.run` — freezes the entire event loop. Every asyncio-scheduled watcher freezes with it: the cycle watchdog, the health monitor's dead-man-switches, all of them run *on* the frozen loop. The process stays alive and may even keep accepting TCP, so the external watchdog's 15-minute stale-events check is the only backstop, it fires late, and it cannot say *what* blocked. This is the root-cause shape of the multi-hour silent stalls (#9486).

Detecting "event loop alive as a process but frozen solid" requires an in-process observer that does not run on the event loop.

## Decision

`src/event_loop_watchdog.py` adds the missing layer: a daemon OS **thread** started by `HydraFlowOrchestrator.run()` in `src/orchestrator.py:HydraFlowOrchestrator.run` alongside the loops.

- **Beacon.** A trivial repeating asyncio task stamps a monotonic timestamp (`EventLoopBeacon`) every 1s. While the loop is synchronously blocked the task is simply never scheduled — which is exactly the signal. The stamp is a GIL-atomic float write; cost is negligible.
- **Detector.** The daemon thread polls the beacon's age against the `event_loop_watchdog_stall_seconds` threshold (default 120s — generous; a true synchronous wedge is multi-minute). One trip per freeze episode, not per poll tick; a fresh beacon closes the episode.
- **On trip (default-ON):** `faulthandler.dump_traceback(all_threads=True)` to a diagnostics file and stderr — the frozen loop thread's top Python frame in that dump *is* the offending call site — plus a stall marker on disk. The thread cannot file a GitHub issue itself (the async Ports run on the very loop that froze), so escalation is split: `HealthMonitorLoop._check_event_loop_stall` in `src/health_monitor_loop.py` consumes the marker on the next healthy cycle (in-place recovery or post-restart) and files one `hydraflow-find` + `loop-stalled` issue, file-then-clear.
- **Hard recovery (default-OFF, opt-in):** with `event_loop_watchdog_hard_restart` enabled, the trip ends with `os._exit(75)` (`EX_TEMPFAIL`) so systemd/docker/launchd restarts a live process. Notify-default / restart-opt-in mirrors the branch-GC and external-liveness-watchdog precedent: automated process termination requires explicit operator consent and a supervisor with `Restart=always`; without one a hard exit turns a frozen process into a dead one.

### Amendment (#11604): the destructive path must attribute the freeze first

The original design armed the restart on the *first* trip, on a wall-clock signal alone. A wall clock cannot distinguish "this loop is wedged" from "this HOST is oversubscribed and nothing got scheduled" — and restarting a starved process adds a fresh startup's worth of load to the host that starved it. That is the failure mode #11604 hit live: the trip fired at 120.9s while two `pytest -n auto` suites and a docker stack shared the machine, and the named frame (`trust_fleet_sanity_loop._collect_window_metrics`) measured 1.8 ms — four orders of magnitude short of a block.

The **notify** half is unchanged and stays sensitive: dump, marker and `loop-stalled` issue fire on the first episode whatever the verdict. Only the **destructive** half is now gated, on two signals the thread already holds:

- **Observer service ratio** — the watchdog thread's own polls taken over the freeze window ÷ the polls its `poll_seconds` cadence called for. A wedged event loop does not stop a separate OS thread waking on time (ratio ≈ 1.0); an oversubscribed host starves the observer alongside the loop. Below `event_loop_watchdog_starvation_service_ratio` (default 0.5) the freeze is classified `starved` and the restart is vetoed. This is the existing observer *self*-reporting from clocks it already reads — no new thread and no new timer, so the "no meta-meta-watcher" non-goal below still holds.
- **Process CPU fraction** — `time.process_time()` burned per wall second. At or above 0.5 the process is demonstrably doing its own work, classifying the freeze `blocked_spin`. A blocking syscall burns none, so this signal can only ever *upgrade* a verdict toward "restart me", never refute a block.

On top of the verdict, the restart requires `event_loop_watchdog_restart_after_episodes` (default 2) accumulated episodes — notify on the first, exit only on a repeat. The counter is the stall marker's pre-existing `episode_count`, which resets when `HealthMonitorLoop` gets a healthy cycle and consumes the marker: recovering well enough to file the issue resets it, while froze→recovered→froze-again climbs it. That is precisely the state where in-place recovery has stopped working. The verdict, the ratios and the decision are written into the marker and surfaced in the filed issue, so an operator reads the attribution before chasing a frame that may be innocent.

The five knobs are Pydantic fields in `src/config.py` surfaced through `src/settings_registry.py` (System tab; everything except `enabled` is re-read live by the thread, `enabled` is captured at startup). They are deliberately *not* in the env-override tables — knobs go to the System tab, secrets stay in `.env`.

One watchdog per process: in multi-repo mode every orchestrator calls `start()`, but they share one event loop, so a process-wide single-flight slot makes all but the first a passive no-op. `stop()` disarms promptly (stop event + bounded join) on any orchestrator exit path; the thread is a daemon regardless, so it can never wedge interpreter shutdown or test teardown.

## Non-goals

Preventing the freezes is out of scope — moving offenders off-loop (`run_in_executor`, `asyncio.create_subprocess_exec`) is a separate, diffuse refactor that this detector's stack dumps exist to prioritise. No meta-meta-watcher: the thread's own liveness is a trivial `Event.wait` poll loop backstopped by the external watchdog. Known limit, accepted: a C extension holding the GIL without release for the whole window defeats any in-process observer, including `faulthandler`; that residual class belongs to the external watchdog.

## Testing boundary

The MockWorld scenario layer is intentionally exempt: thread-level detection of a frozen event loop sits *below* MockWorld's seam (the same rationale that exempts subprocess-internal bounding — MockWorld replays through Ports on a healthy loop and cannot express "the loop itself stopped scheduling"). The behavioral layer is covered instead by `tests/test_event_loop_watchdog.py`, which freezes a real event loop in a child thread with `time.sleep` and asserts detection, dump content, and recovery-callback invocation; the escalation half is covered by `tests/test_health_monitor_event_loop_stall.py`; `tests/regressions/test_issue_9552.py` pins every runtime surface against silent non-delivery (the #9556 lesson), and `tests/regressions/test_issue_11604.py` pins the escalation gates. The #11604 gates are decided by two pure functions (`classify_freeze`, `may_hard_restart`) precisely so the policy is testable without a clock: the real-loop behavioral test opens both gates, because leaving the starvation veto armed there would make its assertion depend on how loaded the CI host is — the very wall-clock sensitivity the veto exists to absorb.

## Consequences

A synchronous block anywhere in the fleet is now detected in ~2 minutes instead of ≥15 (external watchdog) or never (asyncio-level watchers), and every detection produces the one artifact that turns "the factory hung" into a one-line fix: the all-thread stack dump naming the blocking frame. The cost is one daemon thread, one 1s asyncio task, and a third liveness mechanism to keep conceptually distinct — the layering table at the top of `src/event_loop_watchdog.py` is the canonical statement of who catches what. Operators who want lights-off recovery flip one System-tab knob after confirming their supervisor restarts the process.
