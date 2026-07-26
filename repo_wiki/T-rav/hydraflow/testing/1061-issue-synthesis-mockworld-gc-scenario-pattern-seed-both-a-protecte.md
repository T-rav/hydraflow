---
id: 1061
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.545385+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for WorkspaceGCLoop in tests/scenarios/test_loops.py (e.g. test_closed_issue_worktree_destroyed_active_preserved) seed state via _seed_ports(world, workspace_gc_state=...) then run world.run_with_loops(["workspace_gc"], cycles=1), asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass.

Example: always pair a positive and negative case in one scenario run rather than testing preservation alone.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
