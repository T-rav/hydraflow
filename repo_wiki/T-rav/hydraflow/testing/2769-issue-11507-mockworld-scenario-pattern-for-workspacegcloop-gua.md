---
id: 2769
topic: testing
source_issue: 11507
source_phase: plan
created_at: 2026-08-21T02:19:43.269843+00:00
status: active
corroborations: 1
---

# MockWorld scenario pattern for WorkspaceGCLoop guards

New `WorkspaceGCLoop` guard behavior gets a `tests/scenarios/test_workspace_gc_*_scenario.py` file with `pytestmark = pytest.mark.scenario_loops`, sitting beside `test_workspace_gc_all_roots_scenario.py`.

- Build two standard `issue-<N>` worktrees, both closed in `FakeGitHub`.
- Patch `workspace_gc_loop.run_subprocess` to return non-empty diff for one, empty for the other.
- Assert `WorkspacePort.destroy` awaited only for the landed issue and `collected == 1`.

**Why:** Scenario tier exercises the loop end-to-end through `MockWorld` while keeping `run_subprocess` deterministic; unit tests cover contract edges, regression tests cover real-git edges.
