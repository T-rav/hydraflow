---
id: 1422
topic: gotchas
source_issue: 11296
source_phase: plan
created_at: 2026-08-16T02:48:52.749391+00:00
status: active
corroborations: 1
---

# Segment timeline on (issue, stage), not phase_change boundary

`toTimeline` in `src/ui/src/operator/model/timeline.js` must segment on per-issue stage transitions derived from `EVENT_TYPE_TO_STAGE`, not on `phase_change` events. Segment on the tuple `(issue, stage)` so that: repeated same-stage events append to one container; out-of-order events still cluster; global events (no `issue`) append to the open container rather than fragmenting per-issue cards.

**Why:** `phase_change`-as-boundary collapses every non-boundary event into the boot `Idle` card; `(issue, stage)` is the only key that survives reordering and concurrency.
