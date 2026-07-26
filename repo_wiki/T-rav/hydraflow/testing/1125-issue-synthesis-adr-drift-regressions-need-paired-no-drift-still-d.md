---
id: 1125
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.107065+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# ADR drift regressions need paired no-drift + still-drifts checks

When adding a tests/test_adr_drift.py regression for a citation fix, assert both directions: (1) a compute_drift run over a PR touching only the file (no symbol evidence) yields zero findings for that ADR, mirroring test_real_adrs_do_not_drift_on_dependency_only_touches; (2) a diff naming the qualified symbol still drifts, mirroring test_symbol_citation_of_pr_manager_still_drifts. Only the first assertion risks over-suppressing real regressions.

**Why:** a one-sided test (only checking no-drift) can't catch coverage being accidentally suppressed for genuine changes to the cited method.
