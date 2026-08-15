---
id: 1403
topic: gotchas
source_issue: 11247
source_phase: plan
created_at: 2026-08-15T20:03:13.665833+00:00
status: active
corroborations: 1
---

# Fitness e2e tests stub the fetcher, leaving the real seam untested

`tests/scenarios/test_fitness_scorecard_scenario.py` and `test_fitness_scorecard_e2e.py` hand-roll a stub fetcher, so `_make_fitness_issue_fetcher(FakeGitHub)` is never exercised end-to-end.

When changing the fetcher or `FakeGitHub._run_gh`, add a scenario that wires the real fetcher over the fake and asserts closed issues/merged PRs are returned.

**Why:** Stub fetchers hide `KeyError` and missing-field crashes in the real seam; a scenario must fail on `--state` regression rather than pass with an empty window.
