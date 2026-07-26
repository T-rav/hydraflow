---
id: 0033
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:46.852004+00:00
status: active
corroborations: 1
supersedes: 0027,0028,0029,0030,0031
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

Extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop — its class-5 path merges any green, non-draft PR without the `no-auto-merge` label, so the name undersells its generic coverage.

Example: add a new green→merge trigger to `DependabotMergeLoop` instead of creating a parallel loop class.

**Why:** A redundant new loop duplicates logic `DependabotMergeLoop` already implements.
