---
id: 0699
topic: gotchas
source_issue: 10459
source_phase: plan
created_at: 2026-07-24T12:58:41.700627+00:00
status: active
corroborations: 1
---

# WorkspaceGCLoop must check every attempt counter, not just implementation's

`_is_safe_to_gc` in `src/workspace_gc_loop.py` originally only checked the implementation retry-window (`0 < get_issue_attempts < max_issue_attempts`), missing the separate `auto_agent` convergence-ledger counter (`get_auto_agent_attempts` / `auto_agent_max_attempts`). Issue #10403's work was lost because GC swept a worktree mid-auto-agent-session since only one of two independent attempt counters was consulted. When adding new attempt-tracking counters to this repo, audit every retry-window guard (`_is_safe_to_gc`, `_collect_orphaned_branches`) to confirm it checks all counters, not just the first one added.

**Why:** each counter tracks a different in-flight process; checking only one leaves the other's active sessions unprotected from destructive GC sweeps.
