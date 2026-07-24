---
id: 0007
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:33:02.550345+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005
superseded_by: 0011
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

`DependabotMergeLoop`'s class-5 path merges any green, non-draft PR without `no-auto-merge` — the name undersells its actual scope beyond dependency-bump PRs.
Example: don't build a separate loop for generic green→merge automation; extend this one instead.
**Why:** avoids a redundant new loop duplicating logic `DependabotMergeLoop` already implements.
