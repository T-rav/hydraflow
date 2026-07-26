---
id: 1183
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.664696+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in is_real_pid (src/process_group.py) — extend the exclusion set to {1, os.getpid(), os.getppid(), os.getpgrp()}, not just bool, 0, and negative values.

Example: without this, a fake .pid matching init (1) or the test process reaches os.killpg on the reaper's own process group, SIGKILLing the pytest run on Linux. See also: Test os.killpg paths with a spy, not a live signal.

**Why:** Platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
