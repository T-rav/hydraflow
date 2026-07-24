---
id: 0845
topic: testing
source_issue: 10459
source_phase: plan
created_at: 2026-07-24T12:58:41.700681+00:00
status: superseded
corroborations: 1
superseded_by: 0847
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for `WorkspaceGCLoop` in `tests/scenarios/test_loops.py` (e.g. `test_closed_issue_worktree_destroyed_active_preserved`) seed state via `_seed_ports(world, workspace_gc_state=...)` then run `world.run_with_loops(["workspace_gc"], cycles=1)`, asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass. Always pair a positive and negative case in one scenario run rather than testing preservation alone — that's what catches over-broad guards that stop GC throughput entirely.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
