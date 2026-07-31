---
id: 0080
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T04:21:57.758635+00:00
status: active
corroborations: 1
supersedes: 0072
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

Extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop.

Example: Its class-5 path merges any green, non-draft PR without the `no-auto-merge` label; add a new trigger to it instead of creating a parallel loop class. See also: dependencies — Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop.

**Why:** A redundant new loop duplicates logic `DependabotMergeLoop` already implements.
