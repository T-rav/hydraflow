---
id: 0171
topic: architecture
source_issue: 10420
source_phase: plan
created_at: 2026-07-24T06:29:23.521293+00:00
status: active
corroborations: 1
---

# adr_drift.py derive_shared_infra must be a strict superset of the static floor

When adding dynamic suppression logic to `src/adr_drift.py`, any derived set must be `_SHARED_INFRA_MODULES ∪ (dynamic candidates) − vetoes` — never let dynamic logic replace or shrink the hand-curated static floor. Example: `derive_shared_infra(adr_index, *, churn_counts, real_drift_vetoes, min_fanout, min_churn)` in issue #10420's plan unions fan-out+churn candidates onto `_SHARED_INFRA_MODULES` rather than recomputing from scratch.

**Why:** prevents a cold-start regression where known-good suppressed modules (e.g. from #10411's fan-out signal) become unsuppressed on day one because churn data hasn't accumulated yet.
