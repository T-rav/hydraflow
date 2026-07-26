---
id: 0993
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:48:37.204691+00:00
status: active
corroborations: 1
supersedes: 0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895,0896,0897,0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0932,0933,0934,0935,0936,0937,0938,0939
---

# WorkspaceGCLoop must check every attempt counter, not just implementation's

`_is_safe_to_gc` in `src/workspace_gc_loop.py` originally only checked the implementation retry-window (`0 < get_issue_attempts < max_issue_attempts`), missing the separate `auto_agent` convergence-ledger counter (`get_auto_agent_attempts` / `auto_agent_max_attempts`).

Example: issue #10403's work was lost because GC swept a worktree mid-auto-agent-session since only one of two independent attempt counters was consulted. Audit every retry-window guard (`_is_safe_to_gc`, `_collect_orphaned_branches`) to confirm it checks all counters, not just the first one added.

**Why:** each counter tracks a different in-flight process; checking only one leaves the other's active sessions unprotected from destructive GC sweeps.
