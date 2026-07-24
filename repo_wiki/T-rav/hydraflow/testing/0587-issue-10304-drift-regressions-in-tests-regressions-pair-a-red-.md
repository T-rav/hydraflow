---
id: 0587
topic: testing
source_issue: 10304
source_phase: plan
created_at: 2026-07-24T03:55:27.919597+00:00
status: active
corroborations: 1
---

# Drift regressions in tests/regressions/ pair a red content-check with a green mechanism-check

`tests/regressions/test_issue_10304.py` ships two tests: one (`test_adr_0107_reflects_pr_10300_triage_infra_park_split`) is red until the ADR text is fixed — it asserts the ADR body contains a token from `{triage_infra_parked, infra-park, #10290}`; the other (`test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports`) stays green throughout — it proves the drift-detection mechanism itself still fires correctly. Only the first should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
