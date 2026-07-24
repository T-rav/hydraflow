---
id: 0724
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:42:21.205299+00:00
status: active
corroborations: 1
supersedes: 0672,0673,0674,0675,0676,0677,0678,0679,0680,0681,0682,0683,0684,0685,0686,0687,0688,0689,0690,0691,0692,0693,0694,0695,0696,0697,0698,0699,0700,0701,0702,0703,0704,0705,0706,0707,0708,0709,0710,0711
---

# TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers

Changes to `TrustFleetSanityLoop`'s staleness detection require the full pyramid per `docs/standards/testing/README.md`: unit tests in `tests/test_trust_fleet_anomaly_detectors.py` for the floor math, a wiring test in `tests/test_trust_fleet_sanity_loop.py` for call-site fallback behavior, a red→green regression in `tests/regressions/test_issue_10236.py` against real config defaults, and a MockWorld scenario in `tests/scenarios/test_trust_fleet_sanity_scenario.py` covering both a fast-poll/long-cycle worker (no escalation) and an existing slow-poll worker like flake_tracker (escalation unchanged).

**Why:** unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold happen to agree for slow-poll workers but diverge for fast-poll ones — only a scenario exercising both worker profiles proves the fix doesn't regress existing escalations.
