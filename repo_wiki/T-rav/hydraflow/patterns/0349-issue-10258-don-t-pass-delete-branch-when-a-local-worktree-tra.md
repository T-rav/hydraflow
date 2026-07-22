---
id: 0349
topic: patterns
source_issue: 10258
source_phase: plan
created_at: 2026-07-22T09:21:49.448734+00:00
status: superseded
corroborations: 1
superseded_by: 0350
---

# Don't pass --delete-branch when a local worktree tracks the PR branch

When squash-merging a PR via `gh pr merge --squash`, omit `--delete-branch` if a local worktree still references the source branch (e.g. `agent/diag-10215`). Deleting the remote branch out from under an active worktree breaks it; branch cleanup is owned by the GC loop, not the merge step.

**Why:** avoids orphaning a local worktree mid-use by deleting its upstream branch as a side effect of an unrelated merge command.
