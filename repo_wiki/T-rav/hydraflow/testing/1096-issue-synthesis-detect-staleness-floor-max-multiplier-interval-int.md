---
id: 1096
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.002382+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1165
---

# detect_staleness floor: max(multiplier*interval, interval+max_cycle_s)

Floor detect_staleness's threshold in src/trust_fleet_anomaly_detectors.py at `threshold_s = max(multiplier * interval_s, interval_s + max_cycle_s)` instead of a bare `multiplier * interval_s`.

Example: staging_bisect polls every 600s but has cycles up to 2700s; default max_cycle_s=0 (keyword-only) keeps existing callers unaffected.

**Why:** Heartbeats only refresh on cycle completion (src/base_background_loop.py), so a healthy worker can legitimately lag one poll interval plus one full cycle — a flat multiplier misreads that as wedged.
