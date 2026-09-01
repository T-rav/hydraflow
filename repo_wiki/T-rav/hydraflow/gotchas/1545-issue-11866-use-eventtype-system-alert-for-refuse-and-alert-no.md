---
id: 1545
topic: gotchas
source_issue: 11866
source_phase: plan
created_at: 2026-09-01T03:52:25.540795+00:00
status: active
corroborations: 1
---

# Use EventType.SYSTEM_ALERT for refuse-and-alert, not new EventType

When a loop needs to refuse work and alert (e.g., unparseable actor contract), publish `EventType.SYSTEM_ALERT` on the bus with dedup. Do not add a new `EventType`.
- Precedent: `MergeStateWatcherLoop` — bus alert + dedup, no GitHub issue created.
- This removes the event-reducer and `test_events` invariants from scope.
**Why:** New `EventType` values cascade through event-reducer tests and invariants; `SYSTEM_ALERT` already covers the alert-without-issue path.
