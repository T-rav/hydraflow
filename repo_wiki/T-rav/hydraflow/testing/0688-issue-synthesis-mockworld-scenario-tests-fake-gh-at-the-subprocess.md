---
id: 0688
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:08:28.855257+00:00
status: active
corroborations: 1
supersedes: 0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642,0643,0644,0645,0646,0647,0648,0649,0650,0651,0652,0653,0654,0655,0656,0657,0658,0659,0660,0661,0662,0663,0664,0665,0666,0667,0668,0669,0670,0671
---

# MockWorld scenario tests fake gh at the subprocess boundary, not the loop

New shepherd-loop scenarios (e.g. `tests/scenarios/test_green_pr_shepherd_scenario.py`) should use Pattern B (direct loop instantiation, per `test_merge_state_watcher_scenario.py`) and fake `gh` at the subprocess boundary the way `test_merge_policy_scenario.py` does.

Example: assert on `FakeGitHub`-recorded merges, no real subprocess/gh/git calls; tag the module with `pytestmark = pytest.mark.scenario_loops`.

**Why:** keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
