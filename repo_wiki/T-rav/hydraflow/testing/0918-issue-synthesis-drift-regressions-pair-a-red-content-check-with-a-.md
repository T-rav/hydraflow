---
id: 0918
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.786785+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Drift regressions pair a red content-check with a green mechanism-check

`tests/regressions/test_issue_10304.py` ships two tests: one (`test_adr_0107_reflects_pr_10300_triage_infra_park_split`) is red until the ADR text is fixed — it asserts the ADR body contains a token from `{triage_infra_parked, infra-park, #10290}`; the other (`test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports`) stays green throughout, proving the drift-detection mechanism itself still fires correctly.

Example: only the first test should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
