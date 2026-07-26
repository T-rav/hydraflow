---
id: 1194
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.750347+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# ADR-citation drift fixes need no MockWorld/e2e — pure static check

For ADR-citation drift fixes (pure ADR-text plus a static test over a side-effect-free regex parser like _SOURCE_FILE_CITATION_RE), skip MockWorld scenario and sandbox e2e layers despite the repo's usual three-layer pyramid requirement.

Example: the change crosses no pipeline phase, runner, or Port — it has no runtime surface for MockWorld or e2e to exercise.

**Why:** Load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface, so skipping those layers isn't a shortcut.
