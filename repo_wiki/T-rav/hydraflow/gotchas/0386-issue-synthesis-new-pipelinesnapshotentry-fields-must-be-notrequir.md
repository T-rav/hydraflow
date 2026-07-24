---
id: 0386
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.391614+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# New PipelineSnapshotEntry fields must be NotRequired to stay wire-compatible

When adding a new field to a snapshot/wire model consumed by the UI, mark it `NotRequired[...]` in `src/models.py` rather than required — older clients that don't know the field should ignore it, not fail parsing.

Example: `PipelineSnapshotEntry.blocked_reason: NotRequired[str]` is only present on blocked queued entries; `src/ui/src/components/StreamView.jsx`'s `toStreamIssue` maps it when present and the header renders "N queued · M blocked" only when M>0.

**Why:** Required new fields on a shared snapshot schema break any consumer that hasn't been updated in lockstep.
