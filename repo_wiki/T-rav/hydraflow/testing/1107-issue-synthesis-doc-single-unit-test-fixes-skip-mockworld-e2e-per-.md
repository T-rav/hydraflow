---
id: 1107
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.017644+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# Doc+single-unit-test fixes skip MockWorld/e2e per testing standard

A pure ADR-text repair plus one behavioral unit test in tests/test_triage_phase.py — with no change to src/triage_phase.py runtime logic, no new loop/runner, and no new git/gh/subprocess call — legitimately skips MockWorld and sandbox e2e, and skips the ADR-0049 kill-switch requirement.

Example: reserve full-pyramid ADR-0051 review cycles for load-bearing runtime/feature changes.

**Why:** Applying the full test pyramid to a docs-only fix is process overhead that doesn't catch anything a unit test wouldn't.
