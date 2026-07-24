---
id: 0659
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.448111+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# New PipelineSnapshotEntry fields must be NotRequired to stay wire-compatible

When adding a new field to a snapshot/wire model consumed by the UI, mark it `NotRequired[...]` in `src/models.py` rather than required — older clients that don't know the field should ignore it, not fail parsing.

Example: `PipelineSnapshotEntry.blocked_reason: NotRequired[str]` is only present on blocked queued entries; `src/ui/src/components/StreamView.jsx`'s `toStreamIssue` maps it when present and the header renders "N queued · M blocked" only when M>0.

**Why:** Required new fields on a shared snapshot schema break any consumer that hasn't been updated in lockstep.
