---
id: 0942
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-25T01:16:19.627664+00:00
status: active
corroborations: 1
supersedes: 0847,0848,0849,0850,0851,0852,0853,0854,0855,0856,0857,0858,0859,0860,0861,0862,0863,0864,0865,0866,0867,0868,0869,0870,0871,0872,0873,0874,0875,0876,0877,0878,0879,0880,0881,0882,0883,0884,0885,0886,0887,0888,0889,0890,0891,0892,0893,0894,0895
---

# Assert classify call-count==0 to catch dedup-skip regressions in resolver loop

A prior fleet-auto-close attempt stalled because a dedup-skip case wasn't adequately tested — a rollup already fingerprinted in the dedup store got re-triaged anyway.

Example: for any `src/adr_drift_resolver_loop.py` change, write a red-first test asserting `triage.classify` call-count `== 0` when the candidate (per-ADR or `FLEET-<pr>`) is already deduped. Cover at both unit level (`tests/test_adr_drift_resolver_loop.py`) and regression level with a real dedup store.

**Why:** call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
