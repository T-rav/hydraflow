---
id: 1041
topic: gotchas
source_issue: 10577
source_phase: plan
created_at: 2026-07-26T01:40:01.589354+00:00
status: active
corroborations: 1
---

# EscapeLedgerLoop reconcile passes must run before _resolve_range

Any new per-tick logic in `EscapeLedgerLoop` that reacts to resolutions (e.g. closing a surfaced GitHub issue once its escape row is answered) must execute before `_resolve_range` is called, not alongside `_surface_findings`. Quiet ticks short-circuit at `no_new_commits` before reaching later stages, so a reconcile step placed after that point never runs on exactly the ticks where resolutions land.

**Why:** placing it late means resolved escapes silently keep their HITL issue open indefinitely.
