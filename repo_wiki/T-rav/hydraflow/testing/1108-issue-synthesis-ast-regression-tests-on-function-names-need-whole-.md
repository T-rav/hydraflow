---
id: 1108
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:25.930966+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# AST regression tests on function names need whole-token matching

When a regression test checks that a doc/ADR names a specific function (e.g. tests/regressions/test_issue_10302.py checking ADR-0017 names _triage_single_traced), use word-boundary/whole-token matching, not a substring `in` check.

Example: _triage_single is a substring of _triage_single_traced, so a stale ADR that only says _triage_single would incorrectly pass a substring test; use regex \b_triage_single\b vs \b_triage_single_traced\b so the two distinct names can't be conflated.

**Why:** substring matching on function names silently accepts stale references when the new name is an extension of the old one, defeating the point of the regression gate.
