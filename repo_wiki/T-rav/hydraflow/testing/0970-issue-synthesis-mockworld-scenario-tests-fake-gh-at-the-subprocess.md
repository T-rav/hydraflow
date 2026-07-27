---
id: 0970
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.559331+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. tests/scenarios/test_green_pr_shepherd_scenario.py) should use Pattern B (direct loop instantiation, per test_merge_state_watcher_scenario.py) and fake gh at the subprocess boundary the way test_merge_policy_scenario.py does.

Example: assert on FakeGitHub-recorded merges, no real subprocess/gh/git calls; tag the module with pytestmark = pytest.mark.scenario_loops.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
