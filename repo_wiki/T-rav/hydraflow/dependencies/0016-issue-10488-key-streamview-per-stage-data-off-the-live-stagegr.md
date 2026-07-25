---
id: 0016
topic: dependencies
source_issue: 10488
source_phase: review
created_at: 2026-07-25T00:38:26.060853+00:00
status: stale
corroborations: 1
stale_reason: source issue #10488 closed
---

# Key StreamView per-stage data off the live stageGroups array, not static keys

`perStage` in `pipelineCounts.js` is keyed off the exact `stageGroups` array `StreamView` builds via `PIPELINE_STAGES.map(...)` (`StreamView.jsx:335-338`), and `renderFlowStage` consumes members of that same array — not a separately hardcoded stage-key list. This eliminates drift risk if `PIPELINE_STAGES` gains/removes a stage, since there's only one source of truth for stage identity.

**Why:** a parallel static key list would silently go stale (crash or drop a stage) the next time `PIPELINE_STAGES` changes.
