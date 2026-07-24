---
id: 0579
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:13:41.432633+00:00
status: superseded
corroborations: 1
supersedes: 0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566
superseded_by: 0593
---

# TrustFleetSanityLoop staleness tuning needs unit + regression + scenario layers

Changes to `TrustFleetSanityLoop`'s staleness detection require the full pyramid per `docs/standards/testing/README.md`: unit tests in `tests/test_trust_fleet_anomaly_detectors.py` for the floor math itself, a wiring test in `tests/test_trust_fleet_sanity_loop.py` for the call-site fallback behavior, a red→green regression in `tests/regressions/test_issue_10236.py` against real config defaults, and a MockWorld scenario in `tests/scenarios/test_trust_fleet_sanity_scenario.py` verifying both a fast-poll/long-cycle worker (no escalation) and an existing slow-poll worker like flake_tracker (escalation behavior unchanged).

**Why:** unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold happen to agree for slow-poll workers but diverge for fast-poll ones — only a scenario exercising both worker profiles proves the fix doesn't regress existing escalations.
