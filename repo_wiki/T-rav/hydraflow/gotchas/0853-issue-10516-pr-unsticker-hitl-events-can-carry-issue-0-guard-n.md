---
id: 0853
topic: gotchas
source_issue: 10516
source_phase: plan
created_at: 2026-07-25T05:52:44.074249+00:00
status: active
corroborations: 1
---

# pr_unsticker HITL events can carry issue: 0 — guard non-positive issue numbers

`pr_unsticker` emits `hitl_update` events with no `status` field and sometimes `issue: 0` when it can't resolve an issue number. In `useTimeline.js`'s `deriveIssueTimelines()`, treat non-positive/unresolvable issue numbers as "no timeline entry" rather than creating a card for issue `#0`.

**Why:** without the guard, unresolved HITL events from `pr_unsticker` produce a spurious `#0` card in the UI.
