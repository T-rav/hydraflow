---
id: 1179
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.649724+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

StagingPromotionLoop's _cadence_elapsed() check (governed by rc_cadence_hours) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately.

Example: just run ≥2 ticks and assert via a full /api/events scan (not the latest page) to avoid timing flake.

**Why:** Assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
