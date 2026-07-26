---
id: 1239
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:12:37.391245+00:00
status: active
corroborations: 1
supersedes: 1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084,1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1137,1138,1139,1140,1141,1142,1143
---

# Fix wiki-rot cite regex in the extractor, never as a downstream .isdigit() filter

When a cite-extraction bug surfaces in `WikiRotDetectorLoop`, fix `_STYLE_A_RE` in `src/wiki_rot_citations.py` itself (e.g. tighten the symbol group to `[A-Za-z_]\w*`), not with an `.isdigit()` guard in `_check_cite` or the loop.

Example: `tests/regressions/test_issue_10591.py` scans real `docs/wiki/` by calling `extract_cites` directly — a loop-level filter passes the loop's own tests but leaves this pin red, because other consumers (shipped-claim pass, issue bodies, fuzzy suggestions) call `extract_cites` directly.

**Why:** The regex is the single source of truth for what counts as a symbol cite; patching a caller only fixes that one call site and leaves every other consumer exposed.
