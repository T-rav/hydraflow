---
id: 0365
topic: gotchas
source_issue: 10296
source_phase: plan
created_at: 2026-07-22T17:44:18.122262+00:00
status: active
corroborations: 1
---

# New PipelineSnapshotEntry fields must be NotRequired to stay wire-compatible

When adding a new field to a snapshot/wire model consumed by the UI, mark it `NotRequired[...]` in `src/models.py` rather than required — older clients that don't know the field should ignore it, not fail parsing.

Example: `PipelineSnapshotEntry.blocked_reason: NotRequired[str]` is only present on blocked queued entries; `src/ui/src/components/StreamView.jsx`'s `toStreamIssue` maps it when present and the header renders "N queued · M blocked" only when M>0.

**Why:** required new fields on a shared snapshot schema break any consumer that hasn't been updated in lockstep.
