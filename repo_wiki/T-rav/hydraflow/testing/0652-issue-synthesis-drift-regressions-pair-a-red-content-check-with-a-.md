---
id: 0652
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:31:08.498495+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631
---

# Drift regressions pair a red content-check with a green mechanism-check

`tests/regressions/test_issue_10304.py` ships two tests: one (`test_adr_0107_reflects_pr_10300_triage_infra_park_split`) is red until the ADR text is fixed — it asserts the ADR body contains a token from `{triage_infra_parked, infra-park, #10290}`; the other (`test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports`) stays green throughout — it proves the drift-detection mechanism itself still fires correctly. Only the first should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
