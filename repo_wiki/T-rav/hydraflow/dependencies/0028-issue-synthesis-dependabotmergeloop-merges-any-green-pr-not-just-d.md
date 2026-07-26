---
id: 0028
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:53:24.581638+00:00
status: active
corroborations: 1
supersedes: 0023
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

`DependabotMergeLoop`'s class-5 path merges any green, non-draft PR without the `no-auto-merge` label — its name undersells that it covers generic green→merge automation, not just dependency-bump PRs.

Example: extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop.

**Why:** avoids a redundant new loop duplicating logic `DependabotMergeLoop` already implements.
