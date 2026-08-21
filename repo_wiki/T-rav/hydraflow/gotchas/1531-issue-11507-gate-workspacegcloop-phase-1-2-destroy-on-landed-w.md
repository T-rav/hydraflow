---
id: 1531
topic: gotchas
source_issue: 11507
source_phase: plan
created_at: 2026-08-21T02:19:43.269807+00:00
status: active
corroborations: 1
---

# Gate WorkspaceGCLoop phase-1/2 destroy on landed-work guard

In `WorkspaceGCLoop`, issue closure is not a proxy for "the work landed." Gate both the phase-1 state-sweep `remove_workspace` (`src/workspace_gc_loop.py:87-92`) and phase-2 `_collect_orphaned_dirs` destroy on `_worktree_has_unlanded_work` returning False.

- Unlanded → `skipped += 1`, log at warning with a literal format string, **retain** the state entry (evicting state while the dir survives just relands it as a phase-2 orphan).
- Guard must run *after* `_is_safe_to_gc` and *before* destroy.

**Why:** Without the guard, closing the GitHub issue reaps a worktree whose commits were never merged, destroying unlanded work silently.
