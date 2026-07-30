---
id: 0045
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:48:28.316100+00:00
status: superseded
corroborations: 1
supersedes: 0039
superseded_by: 0052
---

# DependabotMergeLoop merges any green PR, not just Dependabot's

Extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop — its class-5 path merges any green, non-draft PR without the `no-auto-merge` label, so the name undersells its generic coverage.

Example: add a new green→merge trigger to `DependabotMergeLoop` instead of creating a parallel loop class. See also: dependencies — Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop.

**Why:** A redundant new loop duplicates logic `DependabotMergeLoop` already implements.
