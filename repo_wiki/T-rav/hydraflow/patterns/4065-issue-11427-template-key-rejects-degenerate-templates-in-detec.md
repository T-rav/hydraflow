---
id: 4065
topic: patterns
source_issue: 11427
source_phase: plan
created_at: 2026-08-18T04:40:50.671756+00:00
status: active
corroborations: 1
---

# template_key rejects degenerate templates in DetectorCalibrationLoop

The public `template_key(norm)` function in `src/detector_calibration_loop.py` replaces each surviving `#\d+` entity ref with a placeholder, then rejects degenerate results.

- Reject if no entity placeholder survives (no `#N` refs at all).
- Reject if fewer than 3 alphabetic tokens remain after stripping.
- Volatile counters still collapse inside the template key (inherited from `_normalize`).

**Why:** Degenerate templates match too broadly — a bare phrase with no entity ref would flag every escalation as spray, producing false positives.
