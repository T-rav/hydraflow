---
id: 0583
topic: testing
source_issue: 10293
source_phase: plan
created_at: 2026-07-22T18:20:50.899455+00:00
status: active
corroborations: 1
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does — assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls. Tag the module with `pytestmark = pytest.mark.scenario_loops`.
**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
