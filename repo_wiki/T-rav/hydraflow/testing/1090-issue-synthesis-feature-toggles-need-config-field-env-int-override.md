---
id: 1090
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:21.994153+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# Feature toggles need config field + _ENV_INT_OVERRIDES tested both ways

Every config toggle requires both a field in src/config.py AND an entry in _ENV_INT_OVERRIDES. Test both the default value and the env-var override path.

Example: the _ENV_INT_OVERRIDES tuple default must equal the Field default or the override silently stops applying. See also: architecture-state-persistence.md — _ENV_INT_OVERRIDES default sync.

**Why:** Without the overrides entry, the env-var has no effect; the toggle appears configurable at runtime but is not.
