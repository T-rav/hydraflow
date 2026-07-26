---
id: 1110
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.021794+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Fresh sandbox has no cadence marker — RC cut fires on tick 1

StagingPromotionLoop's _cadence_elapsed() check (governed by rc_cadence_hours) is true by default when no prior cadence marker exists, so a scenario seeding a fresh sandbox doesn't need to fake or shrink the cadence to get an RC cut immediately.

Example: just run ≥2 ticks and assert via a full /api/events scan (not the latest page) to avoid timing flake.

**Why:** Assuming cadence needs mocking leads to unnecessary scenario complexity; the real gotcha is asserting on the wrong event-page window.
