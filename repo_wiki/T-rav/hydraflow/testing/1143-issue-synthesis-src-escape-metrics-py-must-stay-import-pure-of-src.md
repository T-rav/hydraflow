---
id: 1143
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.068300+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
---

# src/escape/metrics.py must stay import-pure of src/escape/ledger.py

escape/metrics.py may never import from escape/ledger.py — the dependency is one-directional (ledger imports metrics helpers like latest_by_escape, latest_by_id, not the reverse).

Example: when adding new collapse/aggregation logic for the escape ledger, put it in metrics.py even if it feels ledger-specific.

**Why:** Keeps metrics reusable as a pure computation module (used by loop reports, HITL surface, vitals.observe, sampled_audit_loop) without pulling in ledger's file I/O.
