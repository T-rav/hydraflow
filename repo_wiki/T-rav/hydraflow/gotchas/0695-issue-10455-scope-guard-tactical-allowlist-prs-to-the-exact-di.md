---
id: 0695
topic: gotchas
source_issue: 10455
source_phase: plan
created_at: 2026-07-24T12:32:23.750712+00:00
status: superseded
corroborations: 1
superseded_by: 0704
---

# Scope-guard tactical allowlist PRs to the exact diff to avoid parent-issue stall

When splitting a tactical fix off a stalled/broader parent issue (here, #10455 sliced from #10411's validated commit 92c9a12c), enforce the diff at review to just the two string literals plus a lineage comment in `src/adr_drift.py` and the new test file — widening into `_citation_drifts`, config, or the resolver loop reintroduces the complexity that stalled the parent. **Why:** scope creep back into the resolver is the exact failure mode the tactical split was meant to avoid.
