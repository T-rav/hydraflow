---
id: 0618
topic: patterns
source_issue: 10599
source_phase: plan
created_at: 2026-07-26T11:44:58.431594+00:00
status: active
corroborations: 1
---

# EventBus.subscribe() is fan-out with no per-type filter

Subscribe once and filter in the handler — never per-loop. `EventBus.subscribe()` drains every published event into every subscriber's queue regardless of type. If 60 loops each subscribed, each would receive every `TRANSCRIPT_LINE` event.

- `LoopWakeRouterLoop` holds ONE bus subscription across ticks and filters by a `WAKE_RULES` table before calling `BGWorkerManager.trigger()`.

**Why:** Per-loop subscriptions cause O(loops × events) drain cost and silent queue-overflow drops under high-volume event types.
