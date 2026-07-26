---
id: 1145
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.071112+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Wiki code citations must be single-backtick `path:Symbol` spans

wiki_drift_detector.py:32 only recognizes citations written as one backtick span combining path and symbol (e.g. `src/escape/metrics.py:latest_by_id`).

Example: splitting path and symbol across separate spans or plain prose makes the citation invisible to drift checking, so a stale or fictional claim silently passes review.

**Why:** The entry's self-policing correctness depends entirely on this exact, parseable format.
