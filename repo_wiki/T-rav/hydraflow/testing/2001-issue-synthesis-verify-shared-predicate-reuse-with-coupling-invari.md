---
id: 2001
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T12:50:53.327199+00:00
status: superseded
corroborations: 1
supersedes: 1874
superseded_by: 2130
---

# Verify shared-predicate reuse with coupling invariant

For features built on _SHARED_INFRA_MODULES-style suppression logic in src/adr_drift.py, add a dedicated test asserting the new function's output set is exactly equal to what the existing suppression predicate covers.

Example: `assert {p for adr,p in bare_infra_citation_nudges(adrs)} == set_of_suppressed_pairs`.

**Why:** Ordinary example-based tests pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
