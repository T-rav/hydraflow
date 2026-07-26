---
id: 1112
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.024581+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# sandbox_main.py's SANDBOX_SEAMS registry needs a seam per subprocess loop

Every new subprocess-spawning loop must register a seam (config-disable, seed, or mockworld-sentinel) in src/mockworld/sandbox_main.py's SANDBOX_SEAMS registry.

Example: completeness is enforced by tests/architecture/test_sandbox_seam_completeness.py, not by the ADR citation itself.

**Why:** The seam-completeness test is the real PR-time enforcement of the air-gap invariant; ADR-0052 citations should point to it via Enforced-by rather than relying on drift detection over the registry file.
