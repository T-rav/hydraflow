---
id: 1175
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.636326+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's Enforced by pointer is only real enforcement if the target test asserts the actual behavioral claim, not merely touches a related symbol.

Example: ADR-0017's exclusion rule (_maybe_decompose() returning True must skip increment_session_counter("triaged")) had drifted to point at a test that referenced the counter but never checked the exclusion. The fix adds a test asserting counter delta is zero for epic_decomposed routing.

**Why:** A regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
