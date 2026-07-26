---
id: 1122
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.038496+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Pure-function + single log-line changes skip MockWorld/sandbox e2e

A lint check that's a pure function (is_shared_infra) plus one logger.warning call inside an existing loop (adr_reviewer.py's existing review flow) doesn't need a new MockWorld scenario or sandbox e2e test.

Example: only unit tests across tests/test_adr_drift.py, tests/test_adr_pre_validator.py, tests/test_adr_reviewer.py, plus a tests/regressions/ pin.

**Why:** The docs/standards/testing/README.md full pyramid exists for load-bearing loop/orchestrator changes — applying it to a no-new-loop advisory lint is unnecessary overhead.
