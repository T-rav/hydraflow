---
id: 1202
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:08.005568+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# EscapeLedger is append-only: resolutions are new rows, never rewrites

EscapeLedger (src/escape/ledger.py) is append-only — append_resolution adds a new JSONL line carrying encoded_as; the original row stays on disk forever. Any read path (unresolved(), unencoded_aging, encoded_summary in src/escape_ledger_loop.py) must go through read_latest()/latest_by_id or it double-counts.

Example: existing_ids() must contain the id exactly once after supersession, so a re-tick doesn't re-record. See also: Escape ledger two-stage collapse.

**Why:** In-place rewrites would erase false-positive history and silently resurface already-resolved escapes on the HITL surface.
