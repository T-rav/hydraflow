---
id: 0863
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.434131+00:00
status: superseded
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
superseded_by: 0898
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does.

Example: assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls; tag the module with `pytestmark = pytest.mark.scenario_loops`.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
