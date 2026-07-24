---
id: 0893
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.577370+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for `WorkspaceGCLoop` in `tests/scenarios/test_loops.py` (e.g. `test_closed_issue_worktree_destroyed_active_preserved`) seed state via `_seed_ports(world, workspace_gc_state=...)` then run `world.run_with_loops(["workspace_gc"], cycles=1)`, asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass. Always pair a positive and negative case in one scenario run rather than testing preservation alone — that's what catches over-broad guards that stop GC throughput entirely.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
