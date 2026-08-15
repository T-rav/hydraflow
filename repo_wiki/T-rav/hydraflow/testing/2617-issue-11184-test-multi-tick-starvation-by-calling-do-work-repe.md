---
id: 2617
topic: testing
source_issue: 11184
source_phase: plan
created_at: 2026-08-14T23:44:16.701471+00:00
status: active
corroborations: 1
---

# Test multi-tick starvation by calling _do_work repeatedly against same fakes

Test multi-tick deferral in `AdrDriftResolverLoop` by invoking `_do_work()` repeatedly against the same faked harness (state/dedup/PR/LLM), asserting on returned counters, `triage.classify.await_count`, `pr.close_issue` awaits, and `dedup.set_all` calls.

- In `tests/test_adr_drift_resolver_loop.py` fleet-budget class, prove trailing small batches are triaged across consecutive ticks without resetting fakes.
- No MockWorld scenario needed — loop-internal budget arithmetic crosses no phase.

**Why:** Single-tick tests cannot prove deferral-to-next-tick behavior; reusing the same fakes across `_do_work()` calls simulates real loop continuation.
