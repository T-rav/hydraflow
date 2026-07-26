---
id: 1128
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.118740+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Doc-typo ADR fixes still need parser-consumer regression tests

For a citation-repoint fix on ADR-0049 (docs/adr/0049-trust-loop-kill-switch-convention.md), the regression test lives in tests/regressions/test_issue_10444.py and asserts against parse_adr_file() output — that source_files includes src/base_background_loop.py and src/bg_worker_manager.py, and source_symbols maps them to LoopDeps / BGWorkerManager.is_enabled respectively.

Example: classified as not-load-bearing (no pipeline/runner/loop change), so per docs/standards/testing/README.md it skips MockWorld scenario and sandbox e2e.

**Why:** an ADR text edit with no test would let the citation format regress again with no CI signal, same as #9514/#10440.
