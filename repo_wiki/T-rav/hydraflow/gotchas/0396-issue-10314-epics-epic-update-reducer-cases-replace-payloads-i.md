---
id: 0396
topic: gotchas
source_issue: 10314
source_phase: plan
created_at: 2026-07-22T18:34:32.045541+00:00
status: active
corroborations: 1
---

# EPICS/epic_update reducer cases replace payloads instead of merging by epic_number

In `src/ui/src/context/HydraFlowContext.jsx`, the `EPICS` case (~line 589, populated from `/api/epics` → `EpicDetail`) and `epic_update` case (~line 578, populated from WS `epic_update` → `EpicProgress`) each overwrite the epic object wholesale, so whichever payload arrives last wins and the other shape's fields vanish (e.g. `child_issues` from WS disappears on the next REST poll, or `merged_children`/`readiness` from REST disappears on the next WS event). This caused `EpicRow`'s "N issues" count to flicker. Fix by field-union merging keyed by `epic_number`, not replacing.

**Why:** two independent data sources feeding one reducer slot need reconciliation, not last-write-wins, or UI state visibly regresses between polls/events.
