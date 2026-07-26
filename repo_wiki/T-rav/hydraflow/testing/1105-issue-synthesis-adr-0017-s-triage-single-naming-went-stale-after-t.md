---
id: 1105
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.014890+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# ADR-0017's `_triage_single` naming went stale after the #6089/#6190 split

ADRs that name specific functions in their Context rot silently when those functions get extracted. ADR-0017 said increment_session_counter("triaged") lived in _triage_single, but #6089/#6190 moved them to _triage_adr and _triage_single_traced (src/triage_phase.py:550).

Example: when splitting a function an ADR references by name, grep the ADR corpus for the old name before merging.

**Why:** No test caught this because ADR prose isn't type-checked; stale anchors mislead future readers into editing the wrong function.
