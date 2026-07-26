---
id: 1193
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.748117+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

tests/architecture/test_adr_source_citations_exist.py must extract every src/*.py-like candidate substring per ADR and assert _SOURCE_FILE_CITATION_RE.fullmatch succeeds, not just validate already-parsed citations.

Example: exclude placeholders via _is_glob (e.g. `src/<module>.py:<Symbol>`); catch dead tokens like double-colon or trailing parens that fail to parse.

**Why:** Testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
