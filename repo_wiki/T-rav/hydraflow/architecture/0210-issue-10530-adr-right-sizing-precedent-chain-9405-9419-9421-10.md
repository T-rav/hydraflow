---
id: 0210
topic: architecture
source_issue: 10530
source_phase: plan
created_at: 2026-07-25T09:44:02.075260+00:00
status: active
corroborations: 1
---

# ADR right-sizing precedent chain: #9405 → #9419/#9421 → #10400 → #10530

HydraFlow has a recurring, established pattern for fixing over-broad ADR citation drift: qualify bare `path` citations to `path:Symbol` form on multi-concern files, guarded by extending the same regression test each time (`tests/regressions/test_issue_9419_9421_adr_drift.py`). When diagnosing a new false-positive ADR drift rollup (via `_reconcile_stale_rollups`), check whether the cited file is multi-concern (needs `:Symbol`) vs single-purpose/wholly-owned (stays bare) before choosing the fix — don't default to widening `_SHARED_INFRA_MODULES`, which blanket-suppresses drift for all ADRs citing that file, not just the one with the false positive.

**Why:** keeps the fix narrowly scoped instead of reaching for the allowlist lever, which has repo-wide blast radius.
