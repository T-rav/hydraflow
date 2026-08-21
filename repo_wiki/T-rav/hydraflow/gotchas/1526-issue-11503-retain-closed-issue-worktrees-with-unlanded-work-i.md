---
id: 1526
topic: gotchas
source_issue: 11503
source_phase: plan
created_at: 2026-08-21T02:03:56.958112+00:00
status: active
corroborations: 1
---

# Retain closed-issue worktrees with unlanded work indefinitely

Rule: In `_reap_worktree_if_safe` (`src/workspace_gc_loop.py:536`), a closed issue state does NOT authorize reaping a worktree whose work never landed. Apply the landed-or-empty guard uniformly across closed-issue, open-issue, and unattributed paths.

Example: A worktree attributed to a closed-as-not-planned issue but holding commits absent from `origin/<base>` is retained each cycle (logged at debug with a distinguishable literal format string).

**Why:** The #10459/#6413 invariant — disk space is preferable to silently destroying an agent's unpushed commits; the closed state is not authoritative proof of merge.
