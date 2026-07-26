---
id: 1121
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.032084+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# Cleanup/consolidation PRs require full `make quality`, not a targeted subset

Cleanup/consolidation/refactor PRs touching multiple modules must run full make quality (ruff, pyright, tests, jscpd), never a file-targeted pytest subset.

Example: the src/jsonl_ledger.py unification (#10403) required full quality rather than only the three directly-touched ledger test files — tests/test_audit_sample_store.py was added since AuditSampleLedger had only indirect coverage. The same standard applied to the #10411 ADR-drift fan-out suppression and the ledger-subclass refactor across src/audit/store.py, src/escape/ledger.py, src/intervention/ledger.py, src/erosion/trends.py.

**Why:** PR #8460 shipped after a 211-test targeted-file pass went green, but tests/test_audit_prompts.py and tests/test_repo_wiki_loop_pr.py had 7 failures the subset missed, forcing hotfix PR #8463 — cross-module refactors have wider blast radius than their diff.
