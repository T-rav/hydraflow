---
id: 1127
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.045632+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Pure _SHARED_INFRA_MODULES edits need only unit coverage, not MockWorld/e2e

Per docs/standards/testing/README.md's three-layer pyramid, a change confined to adding string literals to _SHARED_INFRA_MODULES in src/adr_drift.py only needs a hermetic unit regression test.

Example: skip MockWorld scenario, sandbox e2e, and ADR-0049 kill-switch — no _citation_drifts/resolver/config edits, no phase-crossing behavior, no new loop/runner, no Ports touched.

**Why:** Those layers exist to catch loop-integration and orchestrator wiring bugs that a pure allowlist-data change cannot introduce.
