---
id: 2589
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:51.949383+00:00
status: active
corroborations: 1
supersedes: 2404
---

# MockWorld scenario tier is release-gating for trust_fleet_sanity

`tests/scenarios/test_trust_fleet_sanity_scenario.py` is the release-gating tier for the sanity loop, using fakes only — no gh/git/subprocess. When modifying staleness or confirmation logic, update existing scenario tests in the same commit: they assume first-tick filing and wall-clock staleness anchors.

Example: the `make quality` gate runs this tier. Sandbox e2e is deliberately skipped when no new loop, runner, or compose service is introduced.

**Why:** Deferring scenario test updates causes red-suite failures late in the cycle.
