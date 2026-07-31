---
id: 0890
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:37:32.660877+00:00
status: superseded
corroborations: 1
supersedes: 0835
superseded_by: 0948
---

# Orphan restore and write-path fix must ship in same PR

Restored wiki entries re-enter synthesis on the next `RepoWikiLoop` tick. If the `WikiCompiler` forward fix (dropping the forced fold) does not ship in the same PR, restored entries get re-folded, recreating the orphan-fold defect (#10566).

- P3 (corpus restore) and P4 (write-path fix) are coupled.
- Shipping one without the other opens a corruption window.

See also: patterns — WikiCompiler forced fold folds unclaimed entries.

**Why:** The restore changes frontmatter state that the write path consumes; the write path must already be fixed or it undoes the restore on the next tick.
