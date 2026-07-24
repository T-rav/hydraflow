---
id: 0613
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:57:59.587771+00:00
status: superseded
corroborations: 1
supersedes: 0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0632
---

# Drift regressions pair a red content-check with a green mechanism-check

`tests/regressions/test_issue_10304.py` ships two tests: one (`test_adr_0107_reflects_pr_10300_triage_infra_park_split`) is red until the ADR text is fixed — it asserts the ADR body contains a token from `{triage_infra_parked, infra-park, #10290}`; the other (`test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports`) stays green throughout — it proves the drift-detection mechanism itself still fires correctly. Only the first should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
