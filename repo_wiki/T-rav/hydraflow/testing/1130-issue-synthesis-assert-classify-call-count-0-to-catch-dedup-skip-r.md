---
id: 1130
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.127226+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Assert classify call-count==0 to catch dedup-skip regressions in resolver loop

A prior fleet-auto-close attempt stalled because a dedup-skip case wasn't adequately tested — a rollup already fingerprinted in the dedup store got re-triaged anyway.

Example: for any src/adr_drift_resolver_loop.py change, write a red-first test asserting triage.classify call-count == 0 when the candidate (per-ADR or FLEET-<pr>) is already deduped. Cover at both unit level (tests/test_adr_drift_resolver_loop.py) and regression level with a real dedup store.

**Why:** call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
