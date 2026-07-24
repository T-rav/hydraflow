---
id: 0816
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T23:38:39.541251+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# WorkspaceGCLoop must check every attempt counter, not just implementation's

`_is_safe_to_gc` in `src/workspace_gc_loop.py` originally only checked the implementation retry-window (`0 < get_issue_attempts < max_issue_attempts`), missing the separate `auto_agent` convergence-ledger counter (`get_auto_agent_attempts` / `auto_agent_max_attempts`).

Example: issue #10403's work was lost because GC swept a worktree mid-auto-agent-session since only one of two independent attempt counters was consulted. Audit every retry-window guard (`_is_safe_to_gc`, `_collect_orphaned_branches`) to confirm it checks all counters, not just the first one added.

**Why:** each counter tracks a different in-flight process; checking only one leaves the other's active sessions unprotected from destructive GC sweeps.
