---
id: 1072
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-26T00:52:52.561760+00:00
status: active
corroborations: 1
supersedes: 0954,0955,0956,0957,0958,0959,0960,0961,0962,0963,0964,0965,0966,0967,0968,0969,0970,0971,0972,0973,0974,0975,0976,0977,0978,0979,0980,0981,0982,0983,0984,0985,0986,0987,0988,0989,0990,0991,0992,0993,0994,0995,0996,0997,0998,0999,1000,1001,1002,1003,1004,1005,1006,1007,1008,1009,1010,1011,1012,1013,1014
---

# ADR source-file citations must be :Symbol-qualified, not bare

A bare `path` citation (e.g. `src/implement_phase.py`) in an ADR's Source-file citations section drifts on *any* touch to that file, even unrelated changes — production feeds `compute_drift` file-level `gh` diffs with no symbol evidence, so a `path:Symbol` citation only drifts when that specific symbol appears in the diff. ADR-0097 held `src/implement_phase.py` and `src/retrospective.py` bare while ADR-0002/0005/0014/0024/0063 already used `:Symbol`; PR #10519 touching unrelated `run_batch` code falsely drifted ADR-0097.

Example: qualify to `` `src/implement_phase.py:ImplementPhase._record_impl_metrics` `` — the whole `path:Symbol` must be one contiguous backtick span or `_SOURCE_FILE_CITATION_RE` (src/adr_drift.py) parses it as bare with an empty symbol set.

**Why:** prevents recurring false-positive drift rollups on multi-concern files touched for unrelated reasons.
