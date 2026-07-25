---
id: 0914
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.775589+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does.

Example: assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls; tag the module with `pytestmark = pytest.mark.scenario_loops`.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
