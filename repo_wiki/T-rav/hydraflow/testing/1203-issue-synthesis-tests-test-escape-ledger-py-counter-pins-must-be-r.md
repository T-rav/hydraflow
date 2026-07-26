---
id: 1203
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:08.008003+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# tests/test_escape_ledger.py counter-pins must be rewritten, not deleted

When src/escape/detect.py's originating_pr semantics change, counter-pin assertions in tests/test_escape_ledger.py must be rewritten to assert the new semantics, not simply removed.

Example: assertions like `originating_pr == 777` near line 207 must be updated to assert the new value, not deleted.

**Why:** A deleted assertion still shows a green test run but proves nothing about the new behavior — flagged as a named pre-mortem risk in the #10498 plan.
