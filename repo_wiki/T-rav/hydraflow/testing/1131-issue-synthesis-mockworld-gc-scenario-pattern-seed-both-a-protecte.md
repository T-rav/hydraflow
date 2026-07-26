---
id: 1131
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.130792+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# MockWorld GC scenario pattern: seed both a protected and a collectable issue

Scenario tests for WorkspaceGCLoop in tests/scenarios/test_loops.py (e.g. test_closed_issue_worktree_destroyed_active_preserved) seed state via _seed_ports(world, workspace_gc_state=...) then run world.run_with_loops(["workspace_gc"], cycles=1), asserting one worktree survives (in-window attempt) while a genuinely closed/exhausted issue's worktree is destroyed in the same pass.

Example: always pair a positive and negative case in one scenario run rather than testing preservation alone.

**Why:** a guard that's too permissive (never collects) is as much a regression as one that's too aggressive (destroys active work), and only a same-pass dual assertion catches the former.
