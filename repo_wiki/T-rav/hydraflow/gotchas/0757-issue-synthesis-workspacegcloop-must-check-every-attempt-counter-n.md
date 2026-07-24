---
id: 0757
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:44:16.344207+00:00
status: active
corroborations: 1
supersedes: 0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671,0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703
---

# WorkspaceGCLoop must check every attempt counter, not just implementation's

`_is_safe_to_gc` in `src/workspace_gc_loop.py` originally only checked the implementation retry-window (`0 < get_issue_attempts < max_issue_attempts`), missing the separate `auto_agent` convergence-ledger counter (`get_auto_agent_attempts` / `auto_agent_max_attempts`).

Example: issue #10403's work was lost because GC swept a worktree mid-auto-agent-session since only one of two independent attempt counters was consulted. When adding new attempt-tracking counters, audit every retry-window guard (`_is_safe_to_gc`, `_collect_orphaned_branches`) to confirm it checks all counters.

**Why:** Each counter tracks a different in-flight process; checking only one leaves the other's active sessions unprotected from destructive GC sweeps.
