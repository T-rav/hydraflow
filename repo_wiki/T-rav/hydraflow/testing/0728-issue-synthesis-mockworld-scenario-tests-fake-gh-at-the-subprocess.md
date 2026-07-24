---
id: 0728
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.211148+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does.

Example: assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls; tag the module with `pytestmark = pytest.mark.scenario_loops`.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
