---
id: 1345
topic: gotchas
source_issue: 11181
source_phase: plan
created_at: 2026-08-14T23:04:04.877807+00:00
status: active
corroborations: 1
---

# LLM budget gates must count call attempts, not successes

Increment any per-tick LLM budget counter immediately before the `await classify()` call site, never inside a success path or except block.

In `src/adr_drift_resolver_loop.py`, `triaged += 1` at :419 ran only after a successful `classify()`; the `(ValueError, RuntimeError)` handler at :399–417 bumped `errors` and continued, so failed calls were invisible to the per-ADR gate at :362 and the fleet gate at :448.

**Why:** Counting only successes lets an all-failing tick spend one call per candidate (unbounded by `max_per_tick`) and inflates the fleet's `remaining_budget`, violating the documented "gated per LLM CALL" guarantee.
