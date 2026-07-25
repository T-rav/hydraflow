---
id: 1011
topic: testing
source_issue: 10530
source_phase: plan
created_at: 2026-07-25T09:44:02.075209+00:00
status: active
corroborations: 1
---

# ADR source-file citations must be :Symbol-qualified, not bare

A bare `path` citation (e.g. `src/implement_phase.py`) in an ADR's Source-file citations section drifts on *any* touch to that file, even unrelated changes — production feeds `compute_drift` file-level `gh` diffs with no symbol evidence, so a `path:Symbol` citation only drifts when that specific symbol appears in the diff. ADR-0097 held `src/implement_phase.py` and `src/retrospective.py` bare while ADR-0002/0005/0014/0024/0063 already used `:Symbol`; PR #10519 touching unrelated `run_batch` code falsely drifted ADR-0097. Fix: qualify to `` `src/implement_phase.py:ImplementPhase._record_impl_metrics` `` — the whole `path:Symbol` must be one contiguous backtick span or `_SOURCE_FILE_CITATION_RE` (src/adr_drift.py) parses it as bare with an empty symbol set.

**Why:** prevents recurring false-positive drift rollups on multi-concern files touched for unrelated reasons.
