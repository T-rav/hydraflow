---
id: 4077
topic: patterns
source_issue: 11503
source_phase: plan
created_at: 2026-08-21T02:03:56.958081+00:00
status: active
corroborations: 1
---

# Use two-dot git diff to detect squash-merged work in worktrees

Rule: In `src/workspace_gc_loop.py`, detect landed work with `git diff --quiet origin/<base> HEAD` (two-dot, two-rev form). Do NOT use `rev-list origin/base..HEAD`, the three-dot diff, or `git cherry` for this.

Example: `_worktree_work_has_landed(path)` runs the two-dot form via `run_subprocess_result`; `returncode == 0` → landed (tree identical to base: squash-merged or empty); any other code → not landed (fail-closed).

**Why:** A squash merge mints a new SHA, so commit-range and cherry-match approaches never converge; only the tree-level two-dot diff reports identity against the base.
