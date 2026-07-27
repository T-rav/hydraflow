---
id: 1197
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:41:12.896701+00:00
status: active
corroborations: 1
supersedes: 1128
---

# Assert classify call-count==0 for dedup-skip regressions

For any src/adr_drift_resolver_loop.py change, write a red-first test asserting triage.classify call-count == 0 when the candidate (per-ADR or FLEET-<pr>) is already deduped.

Example: cover at both unit level (tests/test_adr_drift_resolver_loop.py) and regression level with a real dedup store.

**Why:** Call-count assertions catch silent re-triage that a "does it still close" test would miss, since re-triaging a CONSISTENT batch produces the "right" outcome by accident.
