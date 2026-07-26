---
id: 1086
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:25.834815+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Subprocess CLI stubs (e.g. fake_gh) log calls to JSONL

Replace real CLI dependencies (e.g. gh) in tests with a small script that accepts the same arguments, writes each invocation to a JSONL file, and exits 0.

Example: subprocess_runner = ['python3', 'fake_gh.py'], used across tests/test_auto_pr.py and scenario tests; assert behavior by parsing the log: json.loads(log_path.read_text()).

**Why:** Real subprocess boundaries catch shell-quoting, PATH resolution, and argument-passing bugs that mock-based patches cannot detect.
