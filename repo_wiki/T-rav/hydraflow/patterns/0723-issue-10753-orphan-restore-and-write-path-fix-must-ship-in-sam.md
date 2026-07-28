---
id: 0723
topic: patterns
source_issue: 10753
source_phase: plan
created_at: 2026-07-27T23:48:50.234478+00:00
status: superseded
corroborations: 1
superseded_by: 0779
---

# Orphan restore and write-path fix must ship in same PR

Restored wiki entries re-enter synthesis on the next `RepoWikiLoop` tick. If the `WikiCompiler` forward fix (dropping the forced fold) does not ship in the same PR, restored entries get re-folded, recreating the orphan-fold defect (#10566).

- P3 (corpus restore) and P4 (write-path fix) are coupled.
- Shipping one without the other opens a corruption window.

**Why:** The restore changes frontmatter state that the write path consumes; the write path must already be fixed or it undoes the restore on the next tick.
