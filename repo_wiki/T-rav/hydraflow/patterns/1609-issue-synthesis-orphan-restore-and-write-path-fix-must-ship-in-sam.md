---
id: 1609
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T07:44:05.515901+00:00
status: superseded
corroborations: 1
supersedes: 1524
superseded_by: 1703
---

# Orphan restore and write-path fix must ship in same PR

Restored wiki entries re-enter synthesis on the next `RepoWikiLoop` tick. If the `WikiCompiler` forward fix (dropping the forced fold) does not ship in the same PR, restored entries get re-folded, recreating the orphan-fold defect (#10566).

Example: P3 (corpus restore) and P4 (write-path fix) are coupled. See also: [patterns] — WikiCompiler forced fold folds unclaimed entries.

**Why:** The restore changes frontmatter state that the write path consumes; the write path must already be fixed or it undoes the restore on the next tick.
