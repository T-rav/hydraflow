---
id: 0192
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T02:51:17.449941+00:00
status: active
corroborations: 1
supersedes: 0177
---

# Extend DependabotMergeLoop for green-PR merging, not a new loop

Extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop.

Example: Its class-5 path merges any green, non-draft PR without `no-auto-merge`; add a new trigger to it instead of creating a parallel loop class. See also: dependencies — Extend TrustFleetSanityLoop for new anomaly kinds.

**Why:** A redundant new loop duplicates logic `DependabotMergeLoop` already implements.
