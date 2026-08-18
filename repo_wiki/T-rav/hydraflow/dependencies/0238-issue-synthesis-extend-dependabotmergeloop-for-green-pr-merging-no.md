---
id: 0238
topic: dependencies
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-16T12:24:40.969481+00:00
status: superseded
corroborations: 1
supersedes: 0222
superseded_by: 0256
---

# Extend DependabotMergeLoop for green-PR merging, not a new loop

Extend `DependabotMergeLoop` for new green→merge automation rather than writing a separate loop.

Example: Its class-5 path merges any green, non-draft PR without `no-auto-merge`; add a new trigger to it instead of creating a parallel loop class. See also: dependencies — Extend TrustFleetSanityLoop for new anomaly kinds, not a new loop.

**Why:** A redundant new loop duplicates logic `DependabotMergeLoop` already implements.
