---
id: 1121
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.037075+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

src/adr_drift.py must stay a pure module — no direct imports of state accessors like _SHARED_INFRA_MODULES from other modules. Instead, thread new inputs as parameters through compute_drift, compute_drift_by_adr, and partition_fleet_drift.

Example: `shared_infra: frozenset[str] | None = None` parameter, defaulting to the static set for backward compatibility; loops compute the effective value once per tick.

**Why:** Keeps adr_drift.py unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
