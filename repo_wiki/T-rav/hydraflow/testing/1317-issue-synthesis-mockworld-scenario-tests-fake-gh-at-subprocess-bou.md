---
id: 1317
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T22:47:42.283051+00:00
status: superseded
corroborations: 1
supersedes: 1243
superseded_by: 1392
---

# MockWorld scenario tests fake gh at subprocess boundary

New shepherd-loop scenarios should use Pattern B (direct loop instantiation, per test_merge_state_watcher_scenario.py) and fake gh at the subprocess boundary the way test_merge_policy_scenario.py does.

Example: assert on FakeGitHub-recorded merges, no real subprocess/gh/git calls; tag with `pytestmark = pytest.mark.scenario_loops`.

**Why:** Keeps scenario tests deterministic and fast while still exercising real loop wiring, matching the existing scenario suite's conventions.
