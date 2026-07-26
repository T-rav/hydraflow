---
id: 1198
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.973300+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# MockWorld GC scenario: seed both a protected and a collectable issue

Scenario tests for WorkspaceGCLoop must seed both a protected and a collectable issue in the same run, asserting one worktree survives while the other is destroyed in the same pass.

Example: `_seed_ports(world, workspace_gc_state=...)` then `world.run_with_loops(["workspace_gc"], cycles=1)` — always pair a positive and negative case.

**Why:** A guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
