---
id: 2246
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.826290+00:00
status: active
corroborations: 1
supersedes: 2101
---

# MockWorld scenario tests fake gh at subprocess boundary

New shepherd-loop scenarios should use Pattern B (direct loop instantiation) and fake gh at the subprocess boundary.

Example: assert on FakeGitHub-recorded merges, no real subprocess/gh/git calls; tag with `pytestmark = pytest.mark.scenario_loops`. See `test_merge_policy_scenario.py`.

**Why:** Keeps scenario tests deterministic and fast while still exercising real loop wiring.
