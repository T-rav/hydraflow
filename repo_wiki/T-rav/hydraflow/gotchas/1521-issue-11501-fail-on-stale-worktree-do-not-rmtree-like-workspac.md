---
id: 1521
topic: gotchas
source_issue: 11501
source_phase: plan
created_at: 2026-08-21T01:19:24.541886+00:00
status: active
corroborations: 1
---

# Fail on stale worktree; do not rmtree like workspace.py

When `scripts/hf_worktree.sh` detects a directory that is a registered worktree on the wrong branch, exit non-zero and print the remediation command (`git worktree remove <dir>`). Never delete or repoint the worktree programmatically.

- `src/workspace.py` uses `rmtree` because factory issue worktrees are disposable.
- Agent worktrees created via the helper may hold hand-written work.

**Why:** Silent deletion of a worktree with uncommitted hand-written work is an unrecoverable data-loss failure mode; a non-zero exit forces a human decision.
