---
id: 1242
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:12:37.428243+00:00
status: active
corroborations: 1
supersedes: 1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084,1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1137,1138,1139,1140,1141,1142,1143
---

# docs/wiki/ broken cites split into 4 classes; only line-ref FPs are #10591

`WikiRotDetectorLoop`'s broken-cite count over `docs/wiki/` is not one bug — at #10591 plan time it was 13 total: 5 line-number refs (`orchestrator.py:948`, `phase_utils.py:392`, etc. — the regex FP), 2 doc placeholders (literal `path.py:symbol` examples in prose), 2 module-level constants, and 4 genuine rot needing real doc fixes. Fixing `_STYLE_A_RE` only zeroes the first class; the other three get separate `hydraflow-find` issues.

**Why:** Don't expect `make quality` or the new audit script to report zero broken cites overall after this fix lands — only zero candidates in the line-reference class it targets.
