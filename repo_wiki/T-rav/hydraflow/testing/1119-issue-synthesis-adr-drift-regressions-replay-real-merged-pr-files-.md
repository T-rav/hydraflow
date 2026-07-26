---
id: 1119
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.018456+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# ADR-drift regressions replay real merged PR files through production ADRIndex

Pin ADR citation/drift false-positive fixes by driving real inputs through the production ADRIndex and compute_drift/by_adr entry points (src/adr_drift.py + src/adr_index.py) — never a synthetic mock ADR or a stubbed drift engine.

Example: tests/regressions/test_issue_10384.py, test_issue_10411.py, test_issue_9176.py, and test_issue_10531.py replay the actual merged PR file list (e.g. PR #10519's src/implement_phase.py, src/phase_utils.py) through ADRIndex, asserting real source_symbols output and zero findings for a file-only diff. Pair with a tmp_path-fixture ADR that bare-cites a non-exempt module to prove the auditor still fires generally, plus a self-retiring premise guard that skips if the ADR is absent, non-live, or no longer cites the module.

**Why:** a fixture-only or stubbed test can pass while the live ADR/engine regresses or still fires falsely on production diffs, silently reopening the same rollup.
