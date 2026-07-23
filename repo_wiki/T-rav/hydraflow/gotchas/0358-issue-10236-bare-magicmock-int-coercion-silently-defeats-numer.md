---
id: 0358
topic: gotchas
source_issue: 10236
source_phase: plan
created_at: 2026-07-22T17:17:17.227723+00:00
status: active
corroborations: 1
---

# Bare MagicMock int-coercion silently defeats numeric floor logic in tests

A bare `MagicMock()` coerces to `int(mock) == 1` via `__int__`, so if a test fixture doesn't explicitly stub `bg_workers.cycle_timeout.return_value`, code like `int(bg.cycle_timeout(worker))` silently returns 1 instead of erroring — masking the floor entirely rather than failing loudly.

In `tests/test_trust_fleet_sanity_loop.py` and `tests/regressions/test_issue_10236.py`, always stub `cycle_timeout.return_value` explicitly on the fake `bg_workers` object when testing threshold/floor math.

**Why:** an unstubbed mock doesn't raise — it returns a plausible-looking wrong value (1), so the bug shows up as a confusing threshold mismatch rather than an obvious test error.
