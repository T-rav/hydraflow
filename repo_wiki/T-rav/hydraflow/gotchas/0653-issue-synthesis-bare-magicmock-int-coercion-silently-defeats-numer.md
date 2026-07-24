---
id: 0653
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T13:40:13.441410+00:00
status: active
corroborations: 1
supersedes: 0593,0594,0595,0596,0597,0598,0599,0600,0601,0602,0603,0604,0605,0606,0607,0608,0609,0610,0611,0612,0613,0614,0615,0616,0617,0618,0619,0620,0621,0622,0623,0624,0625,0626,0627,0628,0629,0630,0631,0632,0633,0634,0635,0636,0637,0638,0639,0640,0641,0642
---

# Bare MagicMock int-coercion silently defeats numeric floor logic in tests

Always stub `bg_workers.cycle_timeout.return_value` explicitly when testing threshold/floor math — a bare `MagicMock()` coerces to `int(mock) == 1` via `__int__`.

Example: `tests/test_trust_fleet_sanity_loop.py` and `tests/regressions/test_issue_10236.py` both stub this explicitly on the fake `bg_workers` object; without it, `int(bg.cycle_timeout(worker))` silently returns 1 instead of erroring.

**Why:** An unstubbed mock doesn't raise — it returns a plausible-looking wrong value (1), so the bug shows up as a confusing threshold mismatch rather than an obvious test error.
