---
id: 0619
topic: patterns
source_issue: 10599
source_phase: plan
created_at: 2026-07-26T11:44:58.431686+00:00
status: active
corroborations: 1
---

# BGWorkerManager.trigger(name) wakes BaseBackgroundLoop off-cadence

To wake a loop between cadence ticks, call `BGWorkerManager.trigger(worker_name)` (bg_worker_manager.py:95), which sets `BaseBackgroundLoop._trigger_event` (base_background_loop.py:174). `_sleep_or_trigger()` races that event against the cadence sleep, so the loop wakes promptly without skipping cadence.

- Enables hybrid triggering (cadence + coalesced event wake) without per-loop event subscriptions.

**Why:** External callers cannot reach `_trigger_event` directly; the manager name lookup is the only supported entry point.
