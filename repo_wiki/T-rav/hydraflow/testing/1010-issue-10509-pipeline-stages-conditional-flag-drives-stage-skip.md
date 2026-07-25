---
id: 1010
topic: testing
source_issue: 10509
source_phase: plan
created_at: 2026-07-25T05:02:36.104111+00:00
status: active
corroborations: 1
---

# PIPELINE_STAGES conditional flag drives stage-skip, not hardcoded stage keys

Stage-skip logic (e.g. hiding the `hitl` node when an issue never escalated) should read a `conditional: true` property added to the relevant entry in `src/ui/src/constants.js`'s `PIPELINE_STAGES`, following the existing precedent in `pipelineTracks.js`, rather than special-casing `if (stage === 'hitl')` in derivation code. New derivation logic belongs in `src/ui/src/utils/` (e.g. `stageStatus.js`) once `StreamView.jsx` crosses ~741 lines, per the utils-extraction convention.

**Why:** hardcoded stage-key checks silently miss future conditional stages; a data-driven flag makes the skip rule reusable and testable in isolation.
