---
id: 0892
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T16:22:24.575666+00:00
status: active
corroborations: 1
supersedes: 0798,0799,0800,0801,0802,0803,0804,0805,0806,0807,0808,0809,0810,0811,0812,0813,0814,0815,0816,0817,0818,0819,0820,0821,0822,0823,0824,0825,0826,0827,0828,0829,0830,0831,0832,0833,0834,0835,0836,0837,0838,0839,0840,0841,0842,0843,0844,0845,0846
---

# Assert classify call-count==0 to catch dedup-skip regressions in resolver loop

A prior fleet-auto-close attempt stalled because a dedup-skip case wasn't adequately tested — a rollup already fingerprinted in the dedup store got re-triaged anyway. For any `src/adr_drift_resolver_loop.py` change, write a red-first test asserting `triage.classify` call-count `== 0` when the candidate (per-ADR or `FLEET-<pr>`) is already deduped. Cover at both unit level (`tests/test_adr_drift_resolver_loop.py`) and regression level with a real dedup store.

**Why:** Call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
