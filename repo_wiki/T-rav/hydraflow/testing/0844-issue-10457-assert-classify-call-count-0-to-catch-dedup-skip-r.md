---
id: 0844
topic: testing
source_issue: 10457
source_phase: plan
created_at: 2026-07-24T12:45:53.971893+00:00
status: superseded
corroborations: 1
superseded_by: 0847
---

# Assert classify call-count==0 to catch dedup-skip regressions in resolver loop

A prior fleet-auto-close attempt stalled because a dedup-skip case wasn't adequately tested — a rollup already fingerprinted in the dedup store got re-triaged anyway. For any `src/adr_drift_resolver_loop.py` change, write a red-first test asserting `triage.classify` call-count `== 0` when the candidate (per-ADR or `FLEET-<pr>`) is already deduped. Cover at both unit level (`tests/test_adr_drift_resolver_loop.py`) and regression level with a real dedup store.

**Why:** Call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
