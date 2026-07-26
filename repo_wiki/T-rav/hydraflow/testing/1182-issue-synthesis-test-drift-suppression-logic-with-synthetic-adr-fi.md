---
id: 1182
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.661912+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Test drift-suppression logic with synthetic ADR fixtures in unit tests

In tests/test_adr_drift.py, prove new citation-drift behavior by driving compute_drift/_citation_drifts with a synthetic ADR object carrying the new citation form, plus a bare-citation case as a regression guard.

Example: pair with tests/test_adr_index.py assertions that parse_adr_file correctly parses the citation. See also: ADR-drift regressions replay real merged PR files through production ADRIndex, not fixtures.

**Why:** Keeps drift-logic tests independent of the real ADR's prose, so future edits to docs/adr/0052-sandbox-tier-scenarios.md don't silently break drift-suppression coverage.
