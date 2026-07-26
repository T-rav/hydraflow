---
id: 1137
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.253078+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# escape/detect.py's pure core must stay git-free — no subprocess/gh/git calls

src/escape/detect.py is designed as a pure, git-free detector: classification logic (like the has_skip_regression gate and _origin_pointer) must only operate on already-extracted commit data, never shell out to git/gh/subprocess.

Example: test layering enforces this — tests/test_escape_ledger.py is unit-level pure-function tests, while tests/scenarios/test_escape_ledger_scenario.py uses MockWorld fakes only, no real git/GitHub/subprocess calls even at the scenario layer. Regression spec tests/regressions/test_issue_10498.py is written red-first and must be run to confirm 2/2 FAIL before touching src/.

**Why:** keeping the detector pure lets it be unit-tested deterministically and reused by callers (like audit.crosslink) without pulling in process/network dependencies.
