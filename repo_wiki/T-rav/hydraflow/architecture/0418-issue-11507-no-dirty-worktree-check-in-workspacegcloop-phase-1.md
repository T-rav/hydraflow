---
id: 0418
topic: architecture
source_issue: 11507
source_phase: plan
created_at: 2026-08-21T02:19:43.269834+00:00
status: active
corroborations: 1
---

# No dirty-worktree check in WorkspaceGCLoop phase-1/2 paths

Do **not** add an uncommitted-changes (dirty) check to `WorkspaceGCLoop` phases 1–2, even though the landed guard exists.

- Standard worktrees accumulate `__pycache__`, `node_modules`, and other untracked build artifacts.
- A dirty check would make every standard worktree permanently uncollectable.

**Why:** Build artifacts are not signal for "work not yet landed"; only the committed-tree-vs-`origin/<base>` diff is. The dirty-check concern belongs elsewhere (or nowhere); keep `src/workspace_gc_loop.py` phases 1–2 clean of it.
