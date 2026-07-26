---
id: 1211
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:08.206040+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Escape ledger two-stage collapse: by id, then by detection_ref

Collapse escape_ledger.jsonl rows in two passes: first by id (latest-appended wins), then by detection_ref — an `encoded_as != "none-yet"` row always wins over a bare detector row; otherwise pick strongest confidence (high>medium>low), tie-broken by latest.

Example: lives in src/escape/metrics.py::latest_by_escape, consumed by src/escape/ledger.py::read_latest(). See also: EscapeLedger is append-only.

**Why:** Collapsing by detection_ref alone would let a later none-yet detector rerun silently discard a human append_resolution row for the same commit.
