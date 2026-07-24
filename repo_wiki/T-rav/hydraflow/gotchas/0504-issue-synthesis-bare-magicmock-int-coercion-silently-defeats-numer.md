---
id: 0504
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.777901+00:00
status: active
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
---

# Bare MagicMock int-coercion silently defeats numeric floor logic in tests

Always stub `bg_workers.cycle_timeout.return_value` explicitly when testing threshold/floor math — a bare `MagicMock()` coerces to `int(mock) == 1` via `__int__`.

Example: `tests/test_trust_fleet_sanity_loop.py` and `tests/regressions/test_issue_10236.py` both stub this explicitly on the fake `bg_workers` object; without it, `int(bg.cycle_timeout(worker))` silently returns 1 instead of erroring.

**Why:** An unstubbed mock doesn't raise — it returns a plausible-looking wrong value (1), so the bug shows up as a confusing threshold mismatch rather than an obvious test error.
