---
id: 0999
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T06:21:18.150052+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0951,0952
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for `WorkspaceGCLoop` in `tests/scenarios/test_loops.py` (e.g. `test_closed_issue_worktree_destroyed_active_preserved`) seed state via `_seed_ports(world, workspace_gc_state=...)` then run `world.run_with_loops(["workspace_gc"], cycles=1)`, asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass. Always pair a positive and negative case in one scenario run rather than testing preservation alone — that's what catches over-broad guards that stop GC throughput entirely.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
