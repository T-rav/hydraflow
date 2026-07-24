---
id: 0565
topic: testing
source_issue: 10236
source_phase: plan
created_at: 2026-07-22T17:17:17.227731+00:00
status: superseded
corroborations: 1
superseded_by: 0567
---

# TrustFleetSanityLoop staleness tuning needs unit + regression + scenario layers

Changes to `TrustFleetSanityLoop`'s staleness detection require the full pyramid per `docs/standards/testing/README.md`: unit tests in `tests/test_trust_fleet_anomaly_detectors.py` for the floor math itself, a wiring test in `tests/test_trust_fleet_sanity_loop.py` for the call-site fallback behavior, a red→green regression in `tests/regressions/test_issue_10236.py` against real config defaults, and a MockWorld scenario in `tests/scenarios/test_trust_fleet_sanity_scenario.py` verifying both a fast-poll/long-cycle worker (no escalation) and an existing slow-poll worker like flake_tracker (escalation behavior unchanged).

**Why:** unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold happen to agree for slow-poll workers but diverge for fast-poll ones — only a scenario exercising both worker profiles proves the fix doesn't regress existing escalations.
