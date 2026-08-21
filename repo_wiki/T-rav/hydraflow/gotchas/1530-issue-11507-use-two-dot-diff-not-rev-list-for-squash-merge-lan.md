---
id: 1530
topic: gotchas
source_issue: 11507
source_phase: plan
created_at: 2026-08-21T02:19:43.269777+00:00
status: active
corroborations: 1
---

# Use two-dot diff not rev-list for squash-merge landed detection

When detecting whether a worktree's work has landed on `origin/<base>`, use `git diff --name-only origin/<base> HEAD` (two-dot, two-rev), never `rev-list origin/base..HEAD` or three-dot diff.

- Squash-merged commits produce empty stdout under two-dot diff (the tree matches).
- `rev-list origin/base..HEAD` reports squash-merged work as unlanded → leaks every merged issue's worktree forever.

**Why:** Squash merges rewrite the commit SHA but leave an identical tree; only tree comparison catches them, so `_worktree_has_unlanded_work` in `src/workspace_gc_loop.py` is separate from the rev-list-based `_worktree_has_unmerged_commits` (which is #11503's scope).
