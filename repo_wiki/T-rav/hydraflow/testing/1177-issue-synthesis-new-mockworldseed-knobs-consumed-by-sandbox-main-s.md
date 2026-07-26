---
id: 1177
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T12:17:07.644940+00:00
status: active
corroborations: 1
supersedes: 1085,1086,1087,1088,1089,1090,1091,1092,1093,1094,1095,1096,1097,1098,1099,1100,1101,1102,1103,1104,1105,1106,1107,1108,1109,1110,1111,1112,1113,1114,1115,1116,1117,1118,1119,1120,1121,1122,1123,1124,1125,1126,1127,1128,1129,1130,1131,1132,1133,1134,1135,1136,1137,1138,1139,1140,1141,1142,1143,1144,1145,1146,1147,1148,1149,1150,1151,1152,1153
---

# New MockWorldSeed knobs consumed by sandbox_main skip apply_seed changes

When adding a MockWorldSeed field (e.g. staging_enabled: bool) that only needs to affect the sandbox HTTP harness, wire it in src/mockworld/sandbox_main.py via object.__setattr__ after _apply_sandbox_config_overrides.

Example: leave the in-process apply_seed loader untouched if the relevant catalog builder (e.g. _build_staging_promotion) already forces the same value.

**Why:** Avoids duplicating config-forcing logic across the in-process and sandbox loaders when one already hardcodes the behavior the new knob controls.
