---
id: 1174
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.632197+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# ADR-0017's _triage_single naming went stale after #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said increment_session_counter("triaged") lived in _triage_single, but #6089/#6190 moved them to _triage_adr and _triage_single_traced (src/triage_phase.py:550).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging.

**Why:** No test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function.
