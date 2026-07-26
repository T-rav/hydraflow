---
id: 1105
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:25.919424+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Drift regressions pair a red content-check with a green mechanism-check

tests/regressions/test_issue_10304.py ships two tests: one (test_adr_0107_reflects_pr_10300_triage_infra_park_split) is red until the ADR text is fixed — it asserts the ADR body contains a token from {triage_infra_parked, infra-park, #10290}; the other (test_pr_10300_diff_drifts_adr_0107_exactly_as_issue_10304_reports) stays green throughout, proving the drift-detection mechanism itself still fires correctly.

Example: only the first test should flip during the fix.

**Why:** if both tests were red-then-green, you couldn't tell whether a passing suite meant the ADR was fixed or the detector was broken.
