---
id: 0017
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:42:04.100875+00:00
status: active
corroborations: 1
supersedes: 0011,0012,0013,0014,0015
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

`DependabotMergeLoop`'s class-5 path merges any green, non-draft PR without `no-auto-merge` — the name undersells its actual scope beyond dependency-bump PRs.

Example: don't build a separate loop for generic green→merge automation; extend this one instead.

**Why:** avoids a redundant new loop duplicating logic `DependabotMergeLoop` already implements.
