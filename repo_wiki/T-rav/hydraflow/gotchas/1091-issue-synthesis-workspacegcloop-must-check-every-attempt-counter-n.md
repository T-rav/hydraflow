---
id: 1091
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:44:02.115583+00:00
status: active
corroborations: 1
supersedes: 0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952,0953,0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014,1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1031,1032,1033,1034,1035,1036
---

# WorkspaceGCLoop must check every attempt counter, not just implementation's

`_is_safe_to_gc` in `src/workspace_gc_loop.py` originally only checked the implementation retry-window (`0 < get_issue_attempts < max_issue_attempts`), missing the separate `auto_agent` convergence-ledger counter (`get_auto_agent_attempts` / `auto_agent_max_attempts`).

Example: issue #10403's work was lost because GC swept a worktree mid-auto-agent-session since only one of two independent attempt counters was consulted. Audit every retry-window guard to confirm it checks all counters.

**Why:** Each counter tracks a different in-flight process; checking only one leaves the other's active sessions unprotected from destructive GC sweeps.
