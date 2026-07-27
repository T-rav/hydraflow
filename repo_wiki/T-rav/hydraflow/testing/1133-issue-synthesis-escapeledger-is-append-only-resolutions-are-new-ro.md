---
id: 1133
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.054038+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1202
---

# EscapeLedger is append-only: resolutions are new rows, never rewrites

EscapeLedger (src/escape/ledger.py) is append-only — append_resolution adds a new JSONL line carrying encoded_as; the original row stays on disk forever. Any read path (unresolved(), unencoded_aging, encoded_summary in src/escape_ledger_loop.py) must go through read_latest()/latest_by_id or it double-counts.

Example: existing_ids() must contain the id exactly once after supersession, so a re-tick doesn't re-record.

**Why:** In-place rewrites would erase false-positive history and silently resurface already-resolved escapes on the HITL surface.
