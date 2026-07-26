---
id: 0023
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:40.535158+00:00
status: superseded
corroborations: 1
supersedes: 0017,0018,0019,0020,0021
superseded_by: 0027
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

`DependabotMergeLoop`'s class-5 path merges any green, non-draft PR without the `no-auto-merge` label — its name undersells that it covers generic green→merge automation, not just dependency-bump PRs.

Example: extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop.

**Why:** avoids a redundant new loop duplicating logic `DependabotMergeLoop` already implements.
