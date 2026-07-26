---
id: 1135
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.249084+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# EscapeLedger is append-only: resolutions are new rows, never rewrites

EscapeLedger (src/escape/ledger.py) is append-only — reaching a terminal state (e.g. append_resolution writing encoded_as: detector + regression-test) always appends a new JSONL row for the same id; the original none-yet row stays on disk forever, never rewritten in place.

Example: every read path — existing_ids(), unresolved(), unencoded_aging, encoded_summary.unencoded in src/escape_ledger_loop.py, plus src/escape/metrics.py — must collapse to the latest row per id via read_latest()/latest_by_id, or it double-counts or resurfaces already-resolved escapes. existing_ids() must still contain each id exactly once after supersession, so a re-tick doesn't re-record.

**Why:** the append-only guarantee preserves audit-trail integrity (false-positive history); skipping latest-row dedup silently resurfaces already-resolved escapes on the HITL surface.
