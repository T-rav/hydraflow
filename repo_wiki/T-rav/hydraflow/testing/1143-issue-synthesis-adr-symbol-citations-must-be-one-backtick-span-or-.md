---
id: 1143
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.274903+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# ADR :Symbol citations must be one backtick span or the symbol set parses empty

Splitting a citation like `src/phase_utils.py`:`file_memory_suggestion` across two backtick spans silently reverts the parser to bare-citation behavior — the cited-symbol set comes back empty and drift protection is lost with no error. It must be a single span: `src/phase_utils.py:file_memory_suggestion`.

Example: when narrowing ADR citations (e.g. ADR-0108's B5 row), assert the parsed citation exposes the exact symbol as a regression test, not just that the text superficially contains a colon.

**Why:** this is a silent footgun — the ADR looks correctly narrowed to a human reader but still drifts on every unrelated file touch.
