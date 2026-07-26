---
id: 1186
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.673896+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# ADR-drift regressions replay real merged PR files through ADRIndex

Pin ADR citation/drift false-positive fixes by driving real inputs through the production ADRIndex and compute_drift/by_adr entry points (src/adr_drift.py + src/adr_index.py) — never a synthetic mock ADR or a stubbed drift engine.

Example: tests/regressions/test_issue_10384.py, test_issue_10411.py replay actual merged PR file lists through ADRIndex. Pair with a tmp_path-fixture ADR that bare-cites a non-exempt module to prove the auditor still fires generally. See also: Test drift-suppression logic with synthetic ADR fixtures.

**Why:** A fixture-only or stubbed test can pass while the live ADR/engine regresses or still fires falsely on production diffs, silently reopening the same rollup.
