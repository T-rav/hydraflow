---
id: 1190
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.737571+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Keep src/adr_drift.py pure; inject state via params, don't cross-import

src/adr_drift.py must stay a pure module — no direct imports of state accessors like _SHARED_INFRA_MODULES from other modules. Instead, thread new inputs as parameters through compute_drift, compute_drift_by_adr, and partition_fleet_drift.

Example: `shared_infra: frozenset[str] | None = None` parameter, defaulting to the static set for backward compatibility; loops compute the effective value once per tick.

**Why:** Keeps adr_drift.py unit-testable without state/DB fixtures and preserves the P2 gate's existing behavior for callers that don't pass the new param.
