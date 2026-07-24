---
id: 0380
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.386838+00:00
status: active
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
---

# Bare MagicMock int-coercion silently defeats numeric floor logic in tests

Always stub `bg_workers.cycle_timeout.return_value` explicitly when testing threshold/floor math — a bare `MagicMock()` coerces to `int(mock) == 1` via `__int__`.

Example: `tests/test_trust_fleet_sanity_loop.py` and `tests/regressions/test_issue_10236.py` both stub this explicitly on the fake `bg_workers` object; without it, `int(bg.cycle_timeout(worker))` silently returns 1 instead of erroring.

**Why:** An unstubbed mock doesn't raise — it returns a plausible-looking wrong value (1), so the bug shows up as a confusing threshold mismatch rather than an obvious test error.
