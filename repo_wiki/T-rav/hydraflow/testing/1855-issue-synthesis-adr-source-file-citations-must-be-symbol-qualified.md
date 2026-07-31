---
id: 1855
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T06:59:05.928842+00:00
status: active
corroborations: 1
supersedes: 1750
---

# ADR source-file citations must be :Symbol-qualified, not bare

ADR source-file citations must use `path:Symbol` form (e.g. `src/implement_phase.py:ImplementPhase._record_impl_metrics`), not bare paths — especially on high-churn files like src/mockworld/sandbox_main.py.

Example: ADR-0097 held bare `src/implement_phase.py`; PR #10519 touching unrelated `run_batch` code falsely drifted it. See also: testing — ADR citations must stay bare when fixing drift.

**Why:** Bare citations drift on any file touch; symbol-qualified citations only drift when that specific symbol appears in the diff.
