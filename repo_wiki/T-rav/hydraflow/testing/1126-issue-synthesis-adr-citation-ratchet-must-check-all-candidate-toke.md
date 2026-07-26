---
id: 1126
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.111592+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# ADR citation ratchet must check all candidate tokens, not just parsed ones

tests/architecture/test_adr_source_citations_exist.py originally validated only citations that already matched _SOURCE_FILE_CITATION_RE against source_files — it never asserted that every `src/...py`-shaped token in a live ADR does match the regex, letting dead tokens (double-colon, trailing parens) exist invisibly.

Example: add a token-parity ratchet: extract every lenient src/*.py-like candidate substring per ADR and assert _SOURCE_FILE_CITATION_RE.fullmatch succeeds, excluding placeholders via _is_glob (e.g. src/<module>.py:<Symbol>).

**Why:** testing only the happy path (parsed citations) can't catch citations that fail to parse in the first place — the exact gap that hid ADR-0049's lost coverage.
