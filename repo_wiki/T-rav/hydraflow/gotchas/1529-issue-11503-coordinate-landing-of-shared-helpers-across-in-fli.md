---
id: 1529
topic: gotchas
source_issue: 11503
source_phase: plan
created_at: 2026-08-21T02:03:56.958142+00:00
status: active
corroborations: 1
---

# Coordinate landing of shared helpers across in-flight issue branches

Rule: When two issues (e.g. #11502 and #11503) both modify the same two methods in `src/workspace_gc_loop.py`, rebase or coordinate rather than landing a duplicate helper under a different name.

Example: #11503 supplies `_worktree_work_has_landed`; #11502 (branch `agent/issue-11502`) needs the same predicate for its squash-merge blindness fix. Rebase one branch onto the other instead of emitting a near-duplicate `_worktree_work_landed`.

**Why:** Duplicated predicates diverge silently over time; both issues' invariants depend on identical two-dot git semantics, and divergence reintroduces the data-loss gap.
