---
id: 1132
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.135433+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Verify shared-predicate reuse with a coupling invariant, not spot checks

For features built on _SHARED_INFRA_MODULES-style suppression logic in src/adr_drift.py, add a dedicated test asserting the new function's output set is exactly equal to what the existing suppression predicate covers (not just spot-checked examples).

Example: assert {p for adr,p in bare_infra_citation_nudges(adrs)} matches the set of (adr, path) pairs _citation_drifts suppresses as shared infra.

**Why:** ordinary example-based tests (one shared-infra case, one non-shared case) pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
