---
id: 0945
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T02:46:40.994863+00:00
status: superseded
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
superseded_by: 0953
---

# Verify shared-predicate reuse with a coupling invariant test, not just unit cases

For features built on `_SHARED_INFRA_MODULES`-style suppression logic in `src/adr_drift.py`, add a dedicated test asserting the new function's output set is *exactly* equal to what the existing suppression predicate covers (not just spot-checked examples).

Example: assert `{p for adr,p in bare_infra_citation_nudges(adrs)}` matches the set of (adr, path) pairs `_citation_drifts` suppresses as shared infra.

**Why:** ordinary example-based tests (one shared-infra case, one non-shared case) pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
