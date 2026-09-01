---
id: 2799
topic: testing
source_issue: 11937
source_phase: plan
created_at: 2026-09-01T09:28:20.470698+00:00
status: active
corroborations: 1
---

# Runner frozensets categorize non-blocking WARN checks by purpose

Keep non-blocking WARN frozensets in `scripts/hydraflow_audit/runner.py` distinct by purpose. `CONDITIONAL_CHECKS = frozenset({"P10.8"})` — judges the PR under test, warns on conditional cells. `ADVISORY_CHECKS` — corpus scans (see `tests/test_audit_lineage_check.py:179`). Union both into `_NON_BLOCKING_WARN_CHECKS` (line 103).

Never reuse `ADVISORY_CHECKS` for conditional-cell checks.

**Why:** Conflating the sets muddies semantics — advisory means corpus scan, conditional means PR-under-test with non-blocking violations — and breaks the invariant that P10.8 can never emit a blocking WARN by construction.
