---
id: 0850
topic: gotchas
source_issue: 10515
source_phase: review
created_at: 2026-07-25T09:50:02.028825+00:00
status: superseded
corroborations: 1
superseded_by: 0851
---

# Known gap: active-bucket stamps PROCESSING but real store uses "active"

`terminal-bucket-flow.likec4` previously asserted the active-bucket `PROCESSING` stamp as correct, but the real `IssueStore` actually stamps `"active"` for that bucket — a real, still-open divergence confirmed out of scope for #10515 and left flagged (not silently fixed) in the corrected diagram.

**Why:** avoid re-discovering this as a "new" bug — it's a known, tracked-but-deferred gap between the active-bucket stamp and the diagram/documentation, not a regression from #10515's HITL/MERGED fix.
