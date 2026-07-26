---
id: 0999
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T23:19:07.595633+00:00
status: active
corroborations: 1
supersedes: 0898,0899,0900,0901,0902,0903,0904,0905,0906,0907,0908,0909,0910,0911,0912,0913,0914,0915,0916,0917,0918,0919,0920,0921,0922,0923,0924,0925,0926,0927,0928,0929,0930,0931,0932,0933,0934,0935,0936,0937,0938,0939,0940,0941,0942,0943,0944,0945,0946,0947,0948,0949,0950,0952,0953,0953,0953
---

# Assert classify call-count==0 to catch dedup-skip regressions in resolver loop

A prior fleet-auto-close attempt stalled because a dedup-skip case wasn't adequately tested — a rollup already fingerprinted in the dedup store got re-triaged anyway.

Example: for any src/adr_drift_resolver_loop.py change, write a red-first test asserting triage.classify call-count == 0 when the candidate (per-ADR or FLEET-<pr>) is already deduped. Cover at both unit level (tests/test_adr_drift_resolver_loop.py) and regression level with a real dedup store.

**Why:** Call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
