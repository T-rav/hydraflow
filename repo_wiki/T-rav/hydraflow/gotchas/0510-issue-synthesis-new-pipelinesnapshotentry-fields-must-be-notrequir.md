---
id: 0510
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.782474+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# New PipelineSnapshotEntry fields must be NotRequired to stay wire-compatible

When adding a new field to a snapshot/wire model consumed by the UI, mark it `NotRequired[...]` in `src/models.py` rather than required — older clients that don't know the field should ignore it, not fail parsing.

Example: `PipelineSnapshotEntry.blocked_reason: NotRequired[str]` is only present on blocked queued entries; `src/ui/src/components/StreamView.jsx`'s `toStreamIssue` maps it when present and the header renders "N queued · M blocked" only when M>0.

**Why:** Required new fields on a shared snapshot schema break any consumer that hasn't been updated in lockstep.
