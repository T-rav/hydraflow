---
id: 1125
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.042776+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# ADR-citation drift fixes need no MockWorld/e2e layer — pure static check

For ADR-citation drift fixes (pure ADR-text plus a static test over a side-effect-free regex parser like _SOURCE_FILE_CITATION_RE), skip MockWorld scenario and sandbox e2e layers despite the repo's usual three-layer pyramid requirement.

Example: the change crosses no pipeline phase, runner, or Port — it has no runtime surface for MockWorld or e2e to exercise.

**Why:** Load-bearing-feature test-pyramid rules apply to features that touch runtime behavior; a text/static-analysis-only fix has no runtime surface, so skipping those layers isn't a shortcut.
