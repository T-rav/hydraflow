---
id: 0700
topic: gotchas
source_issue: 10459
source_phase: plan
created_at: 2026-07-24T12:58:41.700660+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Extract shared _in_retry_window helper across all WorkspaceGCLoop phases

GC-safety checks in `src/workspace_gc_loop.py` must be centralized in one `_in_retry_window` helper and reused everywhere a phase decides whether an issue's worktree/branch is collectable — `_is_safe_to_gc` (state phase) and `_collect_orphaned_branches` (orphan `agent/issue-N` branch phase). Adding a guard in only one phase leaves the other free to destroy in-window work via a different code path.

**Why:** GC has multiple independent sweep phases (state, orphan-dir, orphan-branch); a guard fixed in one but not extracted to a shared helper silently reappears as a bug in the others.
