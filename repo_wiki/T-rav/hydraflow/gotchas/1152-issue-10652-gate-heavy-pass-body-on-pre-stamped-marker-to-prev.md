---
id: 1152
topic: gotchas
source_issue: 10652
source_phase: plan
created_at: 2026-07-26T16:08:03.465313+00:00
status: active
corroborations: 1
---

# Gate heavy-pass body on pre-stamped marker to prevent thrash on failure

When splitting a loop into fast-tick + gated heavy pass, stamp the heavy-pass marker *before* the body runs. A failing heavy pass then retries on its own full cadence rather than every fast tick.

- Boot ⇒ first cycle is always a full pass (matches prior behavior)
- `_do_work()` checks `elapsed >= max(health_monitor_interval, effective_tick)` before the heavy body
- `HealthMonitorLoop` stamps marker before heavy checks, not after

**Why:** Post-body stamping causes a 12× retry storm on every 600s tick when the heavy pass raises.
