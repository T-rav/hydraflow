---
id: 1027
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.452620+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# TrustFleetSanityLoop staleness tuning needs unit+regression+scenario layers

Changes to TrustFleetSanityLoop's staleness detection require the full pyramid per docs/standards/testing/README.md: unit tests in tests/test_trust_fleet_anomaly_detectors.py for the floor math, a wiring test in tests/test_trust_fleet_sanity_loop.py for call-site fallback behavior, a red-to-green regression in tests/regressions/test_issue_10236.py against real config defaults, and a MockWorld scenario in tests/scenarios/test_trust_fleet_sanity_scenario.py covering both a fast-poll/long-cycle worker (no escalation) and an existing slow-poll worker like flake_tracker (escalation unchanged).

**Why:** unit tests alone can't catch a scenario where the multiplier-only threshold and the floored threshold agree for slow-poll workers but diverge for fast-poll ones — only a scenario exercising both profiles proves the fix doesn't regress existing escalations.
