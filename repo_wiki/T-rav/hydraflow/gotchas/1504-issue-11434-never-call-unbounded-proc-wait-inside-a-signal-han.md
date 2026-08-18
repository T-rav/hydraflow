---
id: 1504
topic: gotchas
source_issue: 11434
source_phase: review
created_at: 2026-08-18T09:29:47.203051+00:00
status: active
corroborations: 1
---

# Never call unbounded proc.wait() inside a signal handler

In `scripts/quality_host_lock.py`, any `proc.wait()` invoked from within a signal handler must use a bounded `timeout=`. `Popen._wait()` acquires `_waitpid_lock` via a blocking acquire; if the interrupted outer `proc.wait(timeout=POLL_INTERVAL_S)` still holds that non-reentrant lock mid-iteration, the handler self-deadlocks.
- SIGKILL escalation is safe to bound because SIGKILL guarantees group death regardless of which process reaps it.

**Why:** A permanently hung wrapper holds the advisory lock forever — the exact failure class this wrapper exists to eliminate.
