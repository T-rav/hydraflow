---
id: 2622
topic: testing
source_issue: 11193
source_phase: plan
created_at: 2026-08-15T00:39:44.183388+00:00
status: active
corroborations: 1
---

# Enforce shrink-only ratchets with liveness guards

Seed `_GRANDFATHER` frozensets with offenders still unfixed at implement time and guard against stale entries.

- Architecture tests in `tests/architecture/test_adr_regression_pins_self_retire.py` must assert that grandfathered files still violate the rule.
- If a grandfathered file no longer violates, the ratchet fails, forcing its removal from the set.
- Every grandfather entry must name a file that still exists.

**Why:** A grandfather list without a liveness guard silently absorbs new violations, causing the ratchet to ossify.
