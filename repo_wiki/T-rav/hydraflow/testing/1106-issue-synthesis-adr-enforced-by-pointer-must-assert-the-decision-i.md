---
id: 1106
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.016267+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1175
---

# ADR `Enforced by:` pointer must assert the decision itself

An ADR's Enforced by pointer is only real enforcement if the target test asserts the actual behavioral claim, not merely touches a related symbol.

Example: ADR-0017's exclusion rule (_maybe_decompose() returning True must skip increment_session_counter("triaged")) had drifted to point at a test that referenced the counter but never checked the exclusion. The fix adds a test asserting counter delta is zero for epic_decomposed routing.

**Why:** A regex-satisfying but behaviorally-empty enforcement pointer is a silent-green hole — CI stays green even if the exclusion regresses.
