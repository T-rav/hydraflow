---
id: 1527
topic: gotchas
source_issue: 11503
source_phase: plan
created_at: 2026-08-21T02:03:56.958124+00:00
status: active
corroborations: 1
---

# Collapse reap guards to one predicate, no closed-issue special case

Rule: In `_reap_worktree_if_safe` (`src/workspace_gc_loop.py`), apply one predicate on every path: skip when `_worktree_has_unmerged_commits(path)` and not `_worktree_work_has_landed(path)`. Do not branch on issue state inside this method.

Example: Delete the `state != "closed"` special case and the now-dead `_get_issue_state` call in `_reap_worktree_if_safe`; `_is_safe_to_gc` retains its own issue-state consultation unchanged.

**Why:** Per-path exemptions ("closed-as-authoritative") create the exact data-loss bypass this method exists to prevent; a single uniform guard eliminates state-dependent gaps.
