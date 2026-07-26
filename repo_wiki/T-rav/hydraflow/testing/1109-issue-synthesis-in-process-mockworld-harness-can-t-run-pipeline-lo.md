---
id: 1109
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.020412+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# In-process MockWorld harness can't run pipeline + loops together

The in-process test harness runs run_pipeline XOR run_with_loops, never both in one call.

Example: a scenario needing both the standard hydraflow-ready pipeline and StagingPromotionLoop running concurrently (e.g. s82_post_merge_full_machine) must set IN_PROCESS=False so it runs against the real sandbox.

**Why:** Scenarios exercising cross-loop interaction silently can't be expressed via the faster in-process harness — picking IN_PROCESS=True here would just never invoke one of the two loops.
