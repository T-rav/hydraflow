---
id: 0944
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.991063+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for `WorkspaceGCLoop` in `tests/scenarios/test_loops.py` (e.g. `test_closed_issue_worktree_destroyed_active_preserved`) seed state via `_seed_ports(world, workspace_gc_state=...)` then run `world.run_with_loops(["workspace_gc"], cycles=1)`, asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass. Always pair a positive and negative case in one scenario run rather than testing preservation alone — that's what catches over-broad guards that stop GC throughput entirely.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
