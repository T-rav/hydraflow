---
id: 1240
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T20:11:03.049050+00:00
status: superseded
corroborations: 1
supersedes: 1166
superseded_by: 1314
---

# TrustFleetSanityLoop staleness tuning needs 3 test layers

Changes to TrustFleetSanityLoop's staleness detection require the full pyramid per docs/standards/testing/README.md: unit tests in tests/test_trust_fleet_anomaly_detectors.py, a wiring test in tests/test_trust_fleet_sanity_loop.py, a red-to-green regression in tests/regressions/test_issue_10236.py, and a MockWorld scenario in tests/scenarios/test_trust_fleet_sanity_scenario.py covering both fast-poll/long-cycle and slow-poll workers.

**Why:** Unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold agree for slow-poll workers but diverge for fast-poll ones.
