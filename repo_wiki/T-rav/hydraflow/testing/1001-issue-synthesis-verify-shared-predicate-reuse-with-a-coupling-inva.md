---
id: 1001
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.598100+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Verify shared-predicate reuse with a coupling invariant, not spot checks

For features built on _SHARED_INFRA_MODULES-style suppression logic in src/adr_drift.py, add a dedicated test asserting the new function's output set is exactly equal to what the existing suppression predicate covers (not just spot-checked examples).

Example: assert {p for adr,p in bare_infra_citation_nudges(adrs)} matches the set of (adr, path) pairs _citation_drifts suppresses as shared infra.

**Why:** ordinary example-based tests (one shared-infra case, one non-shared case) pass even if the two functions use subtly different membership checks; only a set-equality test catches predicate divergence.
