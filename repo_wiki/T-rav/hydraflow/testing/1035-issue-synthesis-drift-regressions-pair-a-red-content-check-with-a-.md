---
id: 1035
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.474770+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# Drift regressions pair a red content-check with a green mechanism-check

tests/regressions/test_issue_10304.py ships two tests: one (test_adr_0107_reflects_pr_10300_triage_infra_park_split) is red until the ADR text is fixed — it asserts the ADR body contains a token from {triage_infra_parked, infra-park, #10290}; the other (test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports) stays green throughout, proving the drift-detection mechanism itself still fires correctly.

Example: only the first test should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
