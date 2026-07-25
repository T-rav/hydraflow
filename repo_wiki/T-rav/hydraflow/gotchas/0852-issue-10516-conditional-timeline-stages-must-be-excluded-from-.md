---
id: 0852
topic: gotchas
source_issue: 10516
source_phase: plan
created_at: 2026-07-25T05:52:44.074238+00:00
status: active
corroborations: 1
---

# Conditional timeline stages must be excluded from lastDoneIndex rollup

In `useTimeline.js`, `currentStage` is derived from `lastDoneIndex` across the stage sequence. Conditional stages like `hitl` (which sits between `review` and `merged` with `role: null`) must be excluded from that rollup — otherwise a resolved escalation marks `hitl` as `done` and incorrectly advances `currentStage` toward `merged` even when later required stages haven't run. The existing no-role skip in the currentStage loop is the established mechanism for this; conditional stages should reuse it.

**Why:** prevents a resolved HITL escalation from falsely reporting an issue as further along than it is.
