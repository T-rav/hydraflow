---
id: 0603
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.192842+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Bare MagicMock int-coercion silently defeats numeric floor logic in tests

Always stub `bg_workers.cycle_timeout.return_value` explicitly when testing threshold/floor math — a bare `MagicMock()` coerces to `int(mock) == 1` via `__int__`.

Example: `tests/test_trust_fleet_sanity_loop.py` and `tests/regressions/test_issue_10236.py` both stub this explicitly on the fake `bg_workers` object; without it, `int(bg.cycle_timeout(worker))` silently returns 1 instead of erroring.

**Why:** An unstubbed mock doesn't raise — it returns a plausible-looking wrong value (1), so the bug shows up as a confusing threshold mismatch rather than an obvious test error.
