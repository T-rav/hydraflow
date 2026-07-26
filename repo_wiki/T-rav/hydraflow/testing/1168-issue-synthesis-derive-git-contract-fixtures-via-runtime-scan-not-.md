---
id: 1168
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.580697+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# Derive git contract fixtures via runtime scan, not literal strings

In tests/trust/contracts/test_fake_git_contract.py, build _invoke_fake_git's commit summary from a helper that scans the actual fixture dir at test time, not a hardcoded f-string.

Example: scan file list + per-file insertion counts from git_sandbox at test time, so fake output stays in lockstep with fixture contents automatically.

**Why:** A hardcoded summary silently drifted from real git commit output whenever the git_sandbox fixture's file set changed, breaking test_fake_git_matches_cassette[commit] and ContractRefreshLoop's self-heal cycle.
