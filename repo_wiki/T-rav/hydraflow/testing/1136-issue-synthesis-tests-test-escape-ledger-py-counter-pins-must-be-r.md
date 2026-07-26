---
id: 1136
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.251115+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# tests/test_escape_ledger.py counter-pins must be rewritten, not deleted

When src/escape/detect.py's originating_pr semantics change, the counter-pin assertions in tests/test_escape_ledger.py (e.g. originating_pr == 777 near line 207, == 4242 near line 196) must be rewritten to assert the new semantics, not simply removed.

**Why:** a deleted assertion still shows a green test run but proves nothing about the new behavior — this was flagged as a named pre-mortem risk in the #10498 plan, where deletion would silently pass while validating nothing.
