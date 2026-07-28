---
id: 0150
topic: architecture
source_issue: 10314
source_phase: plan
created_at: 2026-07-22T18:34:32.045574+00:00
status: stale
corroborations: 1
stale_reason: no repo-specific anchor (generic best-practice)
---

# Follow the mergeStageIssues precedent for new field-union reducer helpers in HydraFlowContext.jsx

`mergeStageIssues` (`src/ui/src/context/HydraFlowContext.jsx:118`) is the existing pattern for authoritative-incoming reconciliation with field preservation, used for `pipelineIssues` (`HydraFlowContext.jsx:679`). New reducer merge logic (e.g. `mergeEpics` for epic_number-keyed epic state) should mirror this shape: module-local helper function, no `_` prefix, incoming list is authoritative for membership (drops entries absent from server) but merges rather than replaces fields for entries still present.

**Why:** keeps merge semantics consistent across reducer slots so future readers only need to learn the pattern once, and avoids re-deriving reconciliation logic ad hoc per action type.
