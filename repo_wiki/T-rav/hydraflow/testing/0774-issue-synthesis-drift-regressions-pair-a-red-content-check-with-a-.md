---
id: 0774
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:12:20.326413+00:00
status: superseded
corroborations: 1
supersedes: 0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753
superseded_by: 0798
---

# Drift regressions pair a red content-check with a green mechanism-check

`tests/regressions/test_issue_10304.py` ships two tests: one (`test_adr_0107_reflects_pr_10300_triage_infra_park_split`) is red until the ADR text is fixed — it asserts the ADR body contains a token from `{triage_infra_parked, infra-park, #10290}`; the other (`test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports`) stays green throughout, proving the drift-detection mechanism itself still fires correctly.

Example: only the first test should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
