---
id: 0397
topic: gotchas
source_issue: 10314
source_phase: plan
created_at: 2026-07-22T18:34:32.045587+00:00
status: superseded
corroborations: 1
superseded_by: 0402
---

# Epic field taxonomy: progress-only vs detail-only fields in HydraFlowContext epics state

When merging `EpicProgress` (WS `epic_update`) and `EpicDetail` (`/api/epics`) in `state.epics`, progress-only fields are `excluded` and `child_issues`; detail-only fields are `url`, `merged_children`, `active_children`, `queued_children`, `created_at`, `children`, `readiness`, `release`. Neither payload alone carries the union. A generic `{...existing, ...incoming}` merge (not an enumerated field list) is sufficient and preserves this taxonomy without hardcoding it in `HydraFlowContext.jsx`.

**Why:** hardcoding the field list would silently break if either backend payload shape (`EpicProgress`/`EpicDetail`) gains a new field.
