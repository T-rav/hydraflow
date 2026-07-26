---
id: 1142
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T02:29:26.270047+00:00
status: active
corroborations: 1
supersedes: 1015,1016,1017,1018,1019,1020,1021,1022,1023,1024,1025,1026,1027,1028,1029,1030,1031,1032,1033,1034,1035,1036,1037,1038,1039,1040,1041,1042,1043,1044,1045,1046,1047,1048,1049,1050,1051,1052,1053,1054,1055,1056,1057,1058,1059,1060,1061,1062,1063,1064,1065,1066,1067,1068,1069,1070,1071,1072,1073,1074,1075,1076,1077,1078,1079,1080,1081,1082,1083,1084
---

# ADR source-file citations must be :Symbol-qualified, not bare

A bare `path` citation (e.g. `src/implement_phase.py`) in an ADR's Source-file citations section drifts on *any* touch to that file, even unrelated changes — production feeds `compute_drift` file-level `gh` diffs with no symbol evidence, so a `path:Symbol` citation only drifts when that specific symbol appears in the diff. ADR-0097 held `src/implement_phase.py` and `src/retrospective.py` bare while ADR-0002/0005/0014/0024/0063 already used `:Symbol`; PR #10519 touching unrelated `run_batch` code falsely drifted ADR-0097.

Example: qualify to `src/implement_phase.py:ImplementPhase._record_impl_metrics` — the whole `path:Symbol` must be one contiguous backtick span or `_SOURCE_FILE_CITATION_RE` (src/adr_drift.py) parses it as bare with an empty symbol set.

**Why:** prevents recurring false-positive drift rollups on multi-concern files touched for unrelated reasons.
