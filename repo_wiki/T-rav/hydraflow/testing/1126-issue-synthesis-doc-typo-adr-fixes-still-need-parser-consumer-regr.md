---
id: 1126
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.044195+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on an ADR (e.g. ADR-0049), the regression test must assert against parse_adr_file() output — source_files includes the expected modules and source_symbols maps them to the expected symbols.

Example: tests/regressions/test_issue_10444.py asserts ADR-0049's source_files includes src/base_background_loop.py and source_symbols maps to LoopDeps / BGWorkerManager.is_enabled. Classified as not-load-bearing, skips MockWorld/e2e.

**Why:** An ADR text edit with no test would let the citation format regress again with no CI signal.
