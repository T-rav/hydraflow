---
id: 0004
topic: dependencies
source_issue: 10293
source_phase: plan
created_at: 2026-07-22T18:20:50.899440+00:00
status: active
corroborations: 1
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

`DependabotMergeLoop`'s class-5 path merges any green, non-draft PR without `no-auto-merge` — the name undersells its actual scope beyond dependency-bump PRs. Don't build a separate loop for generic green→merge automation; extend this one instead.
**Why:** avoids a redundant new loop duplicating logic `DependabotMergeLoop` already implements.
