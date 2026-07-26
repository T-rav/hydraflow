---
id: 1151
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.346166+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Escape-ledger scenario tests use FakeGitHub + real tiny git repo, tagged scenario_loops

Follow `tests/scenarios/test_escape_ledger_scenario.py` as the template for new escape-ledger scenario tests (e.g. `test_escape_resolution_scenario.py`): real filesystem git repo + `FakeGitHub`, marked `pytestmark = pytest.mark.scenario_loops`, verifying end-to-end that resolving a row removes it from the aging/unencoded surface even after the dedup store is cleared — not just that the JSONL line was appended.

**Why:** a unit test on `resolve_escape` alone can't catch that the HITL issue-generation loop still re-files the same finding after dedup-state reset.
