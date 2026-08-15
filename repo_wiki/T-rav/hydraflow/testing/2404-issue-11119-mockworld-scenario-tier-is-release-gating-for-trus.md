---
id: 2404
topic: testing
source_issue: 11119
source_phase: plan
created_at: 2026-08-14T12:19:29.538028+00:00
status: superseded
corroborations: 1
superseded_by: 2589
---

# MockWorld scenario tier is release-gating for trust_fleet_sanity

`tests/scenarios/test_trust_fleet_sanity_scenario.py` is the release-gating tier for the sanity loop, using fakes only — no gh/git/subprocess. When modifying staleness or confirmation logic, update existing scenario tests in the same commit: they assume first-tick filing and wall-clock staleness anchors.

- The `make quality` gate runs this tier
- Sandbox e2e is deliberately skipped when no new loop, runner, or compose service is introduced
- The MockWorld tier already exercises the full tick path

**Why:** Deferring scenario test updates causes red-suite failures late in the cycle.
