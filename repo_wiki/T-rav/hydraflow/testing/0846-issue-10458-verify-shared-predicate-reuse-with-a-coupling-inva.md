---
id: 0846
topic: testing
source_issue: 10458
source_phase: plan
created_at: 2026-07-24T13:01:26.369155+00:00
status: active
corroborations: 1
---

# Verify shared-predicate reuse with a coupling invariant test, not just unit cases

For features built on `_SHARED_INFRA_MODULES`-style suppression logic in `src/adr_drift.py`, add a dedicated test asserting the new function's output set is *exactly* equal to what the existing suppression predicate covers (not just spot-checked examples). Example: assert `{p for adr,p in bare_infra_citation_nudges(adrs)}` matches the set of (adr, path) pairs `_citation_drifts` suppresses as shared infra. **Why:** ordinary example-based tests (one shared-infra case, one non-shared case) pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
