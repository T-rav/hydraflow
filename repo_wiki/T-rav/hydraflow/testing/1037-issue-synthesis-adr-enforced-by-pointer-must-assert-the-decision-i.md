---
id: 1037
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.481733+00:00
status: superseded
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
superseded_by: 1085
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's Enforced by pointer is only real enforcement if the target test asserts the actual behavioral claim, not merely touches a related symbol. ADR-0017's exclusion rule (_maybe_decompose() returning True must skip increment_session_counter("triaged")) had drifted to point at a test that referenced the counter but never checked the exclusion.

Example: the real fix adds a test in tests/test_triage_phase.py asserting the counter delta is zero when routing_outcome == "epic_decomposed" and exactly one when routing_outcome == "plan".

**Why:** a regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
