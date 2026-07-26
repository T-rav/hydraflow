---
id: 1031
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.463612+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. tests/scenarios/test_green_pr_shepherd_scenario.py) should use Pattern B (direct loop instantiation, per test_merge_state_watcher_scenario.py) and fake gh at the subprocess boundary the way test_merge_policy_scenario.py does.

Example: assert on FakeGitHub-recorded merges, no real subprocess/gh/git calls; tag the module with pytestmark = pytest.mark.scenario_loops.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
