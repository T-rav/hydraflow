---
id: 1131
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T10:47:22.051206+00:00
status: superseded
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1079,1080,1081,1082,1083,1084
superseded_by: 1154
---

# Regression tests for wiki-lint drift should assert the full live-wiki lint

For drift regressions, write tests/regressions/*.py to assert `lint_paraphrases(TermStore(terms).list(), docs/wiki) == []` across the entire live wiki, not just the one flagged term file.

Example: mirrors and reinforces tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki.

**Why:** A narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
