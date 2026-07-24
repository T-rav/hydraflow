---
id: 0894
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T15:47:48.237545+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# Verify shared-predicate reuse with a coupling invariant test, not just unit cases

For features built on `_SHARED_INFRA_MODULES`-style suppression logic in `src/adr_drift.py`, add a dedicated test asserting the new function's output set is *exactly* equal to what the existing suppression predicate covers (not just spot-checked examples).

Example: assert `{p for adr,p in bare_infra_citation_nudges(adrs)}` matches the set of (adr, path) pairs `_citation_drifts` suppresses as shared infra.

**Why:** ordinary example-based tests (one shared-infra case, one non-shared case) pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
