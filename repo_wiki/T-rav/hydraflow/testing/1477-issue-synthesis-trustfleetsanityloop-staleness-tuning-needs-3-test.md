---
id: 1477
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-28T19:46:33.704352+00:00
status: active
corroborations: 1
supersedes: 1389
---

# TrustFleetSanityLoop staleness tuning needs 3 test layers

Changes to TrustFleetSanityLoop's staleness detection require the full pyramid per docs/standards/testing/README.md: unit tests in tests/test_trust_fleet_anomaly_detectors.py, a wiring test in tests/test_trust_fleet_sanity_loop.py, a red-to-green regression in tests/regressions/test_issue_10236.py, and a MockWorld scenario.

**Why:** Unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold agree for slow-poll workers but diverge for fast-poll ones.
