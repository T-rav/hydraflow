---
id: 1154
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.470032+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# PRManager changes must mirror in FakeGitHub

When PRManager (src/pr_manager.py) gains a new query method or side effect, register equivalent behavior in FakeGitHub (src/mockworld/fakes/fake_github.py) in the same change.

Example: isDraft/finditer fix mirrored into the fake; close_issue side effect stripping active stage labels also mirrored.

**Why:** MockWorld scenario tests only catch loop-integration bugs if the fake replicates real adapter semantics, not just signatures.
