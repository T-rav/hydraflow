---
id: 1195
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.752447+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on an ADR (e.g. ADR-0049), the regression test must assert against parse_adr_file() output — source_files includes the expected modules and source_symbols maps them to the expected symbols.

Example: tests/regressions/test_issue_10444.py asserts ADR-0049's source_files includes src/base_background_loop.py and source_symbols maps to LoopDeps / BGWorkerManager.is_enabled. Classified as not-load-bearing, skips MockWorld/e2e.

**Why:** An ADR text edit with no test would let the citation format regress again with no CI signal.
