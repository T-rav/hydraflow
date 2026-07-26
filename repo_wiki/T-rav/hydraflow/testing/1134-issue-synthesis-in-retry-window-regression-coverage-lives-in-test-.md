---
id: 1134
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.246873+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# `_in_retry_window()` regression coverage lives in test_issue_10459.py

Production behavior for _in_retry_window() in src/workspace_gc_loop.py is already covered by tests/regressions/test_issue_10459.py; when a browser/scenario test fails against this function, treat it as test-side drift and fix the mock, not the production code or add new unit tests.

Example: if a fix here seems to require touching src/, that's a signal the scope has grown beyond test drift and needs re-scoping.

**Why:** keeps regression coverage centralized in one place instead of duplicating retry-window assertions across scenario layers.
