---
id: 1212
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:12:37.026039+00:00
status: active
corroborations: 1
supersedes: 1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084,1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1137,1138,1139,1140,1141,1142,1143
---

# Gate dedup fingerprint writes on PRPort.create_issue success

Mark a dedup key spent only after `create_issue` returns successfully — never before. `PRPort.create_issue` (`src/ports.py:366`) is fail-soft (returns `0` on failure), so bind the return and `continue` on falsy before writing `surfaced:<reason>:<id>` in `EscapeLedgerLoop._surface_findings` (`src/escape_ledger_loop.py:409`).

Example: on `0` return, log a warning and skip the `set_all` dedup write so the finding re-surfaces next tick. `CreditExhaustedError` must still propagate unchanged per `reraise_on_credit_or_bug`. See also: this topic — "EscapeLedgerLoop cursor advances unconditionally even on filing failure".

**Why:** Writing keys before the call completes permanently burns retry budget for issues never actually created, since EscapeLedger keys are never retroactively un-spent.
