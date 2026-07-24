---
id: 0609
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.584191+00:00
status: active
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does — assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls. Tag the module with `pytestmark = pytest.mark.scenario_loops`.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
