# ADR-0106: Thread-level event-loop freeze detector

**Status:** Accepted
**Date:** 2026-07-20
**Enforcement:** enforced
**Enforced by:** pytest:tests/regressions/test_issue_9552.py

## Context

HydraFlow's liveness story had three layers with a hole in the middle. The per-cycle asyncio watchdog (#9455 / #9556, `src/base_background_loop.py`) bounds every `_do_work()` cycle — but it is itself an `await asyncio.wait(...)`, so it can only cancel a cycle that is blocked *on an await*. The external liveness watchdog (#10009, `scripts/factory_liveness_watchdog.py`) runs outside the process via cron/launchd and catches whole-process death or a wedged `/healthz`. The hole (#9552): a **synchronous** block inside any loop's `_do_work` — a CPU spin, blocking file I/O, a non-async `subprocess.run` — freezes the entire event loop. Every asyncio-scheduled watcher freezes with it: the cycle watchdog, the health monitor's dead-man-switches, all of them run *on* the frozen loop. The process stays alive and may even keep accepting TCP, so the external watchdog's 15-minute stale-events check is the only backstop, it fires late, and it cannot say *what* blocked. This is the root-cause shape of the multi-hour silent stalls (#9486).

Detecting "event loop alive as a process but frozen solid" requires an in-process observer that does not run on the event loop.

## Decision

`src/event_loop_watchdog.py` adds the missing layer: a daemon OS **thread** started by `HydraFlowOrchestrator.run()` in `src/orchestrator.py` alongside the loops.

- **Beacon.** A trivial repeating asyncio task stamps a monotonic timestamp (`EventLoopBeacon`) every 1s. While the loop is synchronously blocked the task is simply never scheduled — which is exactly the signal. The stamp is a GIL-atomic float write; cost is negligible.
- **Detector.** The daemon thread polls the beacon's age against the `event_loop_watchdog_stall_seconds` threshold (default 120s — generous; a true synchronous wedge is multi-minute). One trip per freeze episode, not per poll tick; a fresh beacon closes the episode.
- **On trip (default-ON):** `faulthandler.dump_traceback(all_threads=True)` to a diagnostics file and stderr — the frozen loop thread's top Python frame in that dump *is* the offending call site — plus a stall marker on disk. The thread cannot file a GitHub issue itself (the async Ports run on the very loop that froze), so escalation is split: `HealthMonitorLoop._check_event_loop_stall` in `src/health_monitor_loop.py` consumes the marker on the next healthy cycle (in-place recovery or post-restart) and files one `hydraflow-find` + `loop-stalled` issue, file-then-clear.
- **Hard recovery (default-OFF, opt-in):** with `event_loop_watchdog_hard_restart` enabled, the trip ends with `os._exit(75)` (`EX_TEMPFAIL`) so systemd/docker/launchd restarts a live process. Notify-default / restart-opt-in mirrors the branch-GC and external-liveness-watchdog precedent: automated process termination requires explicit operator consent and a supervisor with `Restart=always`; without one a hard exit turns a frozen process into a dead one.

The three knobs are Pydantic fields in `src/config.py` surfaced through `src/settings_registry.py` (System tab; threshold and hard-restart are re-read live by the thread, enabled is captured at startup). They are deliberately *not* in the env-override tables — knobs go to the System tab, secrets stay in `.env`.

One watchdog per process: in multi-repo mode every orchestrator calls `start()`, but they share one event loop, so a process-wide single-flight slot makes all but the first a passive no-op. `stop()` disarms promptly (stop event + bounded join) on any orchestrator exit path; the thread is a daemon regardless, so it can never wedge interpreter shutdown or test teardown.

## Non-goals

Preventing the freezes is out of scope — moving offenders off-loop (`run_in_executor`, `asyncio.create_subprocess_exec`) is a separate, diffuse refactor that this detector's stack dumps exist to prioritise. No meta-meta-watcher: the thread's own liveness is a trivial `Event.wait` poll loop backstopped by the external watchdog. Known limit, accepted: a C extension holding the GIL without release for the whole window defeats any in-process observer, including `faulthandler`; that residual class belongs to the external watchdog.

## Testing boundary

The MockWorld scenario layer is intentionally exempt: thread-level detection of a frozen event loop sits *below* MockWorld's seam (the same rationale that exempts subprocess-internal bounding — MockWorld replays through Ports on a healthy loop and cannot express "the loop itself stopped scheduling"). The behavioral layer is covered instead by `tests/test_event_loop_watchdog.py`, which freezes a real event loop in a child thread with `time.sleep` and asserts detection, dump content, and recovery-callback invocation; the escalation half is covered by `tests/test_health_monitor_event_loop_stall.py`; `tests/regressions/test_issue_9552.py` pins every runtime surface against silent non-delivery (the #9556 lesson).

## Consequences

A synchronous block anywhere in the fleet is now detected in ~2 minutes instead of ≥15 (external watchdog) or never (asyncio-level watchers), and every detection produces the one artifact that turns "the factory hung" into a one-line fix: the all-thread stack dump naming the blocking frame. The cost is one daemon thread, one 1s asyncio task, and a third liveness mechanism to keep conceptually distinct — the layering table at the top of `src/event_loop_watchdog.py` is the canonical statement of who catches what. Operators who want lights-off recovery flip one System-tab knob after confirming their supervisor restarts the process.
