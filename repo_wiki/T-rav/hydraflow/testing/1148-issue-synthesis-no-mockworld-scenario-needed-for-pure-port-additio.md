---
id: 1148
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.330667+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# No MockWorld scenario needed for pure Port additions with no consumer

Per docs/standards/testing/README.md's three-layer pyramid, a `tests/scenarios/` MockWorld scenario is skipped when a new Port method has no orchestrator/runner consumer yet — a scenario would only assert the fake against itself, same reasoning as existing boot-time-infra exemptions. Unit test (adapter argv) + ADR-0047 cassette + `tests/test_ports.py`/`tests/test_mockworld_runtime_conformance.py` parity checks are the gating layer instead.

**Why:** prevents writing a scenario test that can't fail meaningfully, which would give false confidence without covering real loop integration.
