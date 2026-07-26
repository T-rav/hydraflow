---
id: 0620
topic: patterns
source_issue: 10599
source_phase: plan
created_at: 2026-07-26T11:44:58.431706+00:00
status: active
corroborations: 1
---

# Short BaseBackgroundLoop intervals cause status-event churn

Set `_INTERVAL_BOUNDS` floor ≥60s for any loop whose `_do_work` publishes `BACKGROUND_WORKER_STATUS` every tick.

- `loop_wake_router` defaults to ≥60s — wake latency is dominated by the coalesce window, not the tick interval.
- Each tick writes status into history + on-disk event log.

**Why:** Sub-60s intervals flood the event log and bus with status noise, crowding out real diagnostic events and risking the 500-slot subscriber queue overflow.
