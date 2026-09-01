---
id: 2793
topic: testing
source_issue: 11866
source_phase: plan
created_at: 2026-09-01T03:52:25.540693+00:00
status: active
corroborations: 1
---

# Pin dedup window from cron clause, not now(), to prevent double-spend

When deduping background loop dispatches through `DedupStore`, the scheduled window must be an explicit field on the selection result, not derived from `now()` at tick time.
- If `now()` derives the window, every tick is its own window → the double-tick test passes but production double-spends budget.
- Assert two ticks inside one scheduled window share the same window field.
**Why:** A re-dispatched window spends real budget twice, and the unit test cannot catch it if the window key is non-deterministic.
