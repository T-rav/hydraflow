---
id: 1114
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.027375+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1183
---

# is_real_pid must exclude self/parent/init pgids, not just bool/0/negative

Exclude self/parent/init pgids in is_real_pid (src/process_group.py) — extend the exclusion set to {1, os.getpid(), os.getppid(), os.getpgrp()}, not just bool, 0, and negative values.

Example: without this, a fake .pid matching init (1) or the test process reaches os.killpg on the reaper's own process group, SIGKILLing the pytest run on Linux (macOS masks it as benign EPERM).

**Why:** Platform-divergent signal semantics (EPERM on macOS vs success on Linux) hide this class of bug from local dev entirely — it only surfaces in CI.
