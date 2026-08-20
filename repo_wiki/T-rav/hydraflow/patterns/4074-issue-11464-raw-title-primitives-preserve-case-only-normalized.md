---
id: 4074
topic: patterns
source_issue: 11464
source_phase: plan
created_at: 2026-08-20T06:25:26.202152+00:00
status: active
corroborations: 1
---

# Raw-title primitives preserve case; only normalized wrappers lowercase

A raw-title substitution primitive must preserve case and leave bare digit runs untouched; only the public normalized wrapper applies `.lower()`. In `src/detector_calibration_loop.py`, `_template_key("Retry 3 of 5 for #7")` → `"Retry 3 of 5 for #N"` — bare `3`/`5` stay, `#7` collapses to `#N`. `template_key` then lowercases the whole result.

**Why:** Breaking this contract causes template-key collisions and false dedup in `DetectorCalibrationLoop`.
