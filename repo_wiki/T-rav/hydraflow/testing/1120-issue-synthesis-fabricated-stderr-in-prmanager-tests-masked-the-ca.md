---
id: 1120
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.035687+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# Fabricated stderr in PRManager tests masked the cannot/can-not bug

Source fixture strings from actual gh CLI output verbatim in PRManager tests, rather than fabricating the expected error string.

Example: tests/test_pr_manager_core.py::test_submit_review_raises_self_review_error_on_approve_own_pr fed fabricated "Cannot approve your own pull request" but real output is "Review Can not approve your own pull request (addPullRequestReview)".

**Why:** Unit tests that fabricate the external error string instead of copying it verbatim can pass while the real integration is broken.
