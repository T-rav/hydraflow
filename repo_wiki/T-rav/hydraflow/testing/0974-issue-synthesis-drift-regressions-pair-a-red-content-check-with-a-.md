---
id: 0974
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.564177+00:00
status: superseded
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
superseded_by: 1015
---

# Drift regressions pair a red content-check with a green mechanism-check

tests/regressions/test_issue_10304.py ships two tests: one (test_adr_0107_reflects_pr_10300_triage_infra_park_split) is red until the ADR text is fixed — it asserts the ADR body contains a token from {triage_infra_parked, infra-park, #10290}; the other (test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports) stays green throughout, proving the drift-detection mechanism itself still fires correctly.

Example: only the first test should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
