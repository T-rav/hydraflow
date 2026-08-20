---
id: 4072
topic: patterns
source_issue: 11464
source_phase: plan
created_at: 2026-08-20T06:25:26.202108+00:00
status: active
corroborations: 1
---

# Delegate template_key to _template_key to avoid duplicate substitution

Refactor a public substitution function to delegate to its private primitive rather than maintaining a parallel `subn` body. In `src/detector_calibration_loop.py`, `template_key(norm)` now ends with `return _template_key(norm).lower()` — both rejection guards stay unchanged, output stays byte-identical (`#N`.lower() == `#n`). One regex `_ENTITY_REF_RE`, one substitution engine.

**Why:** Two near-duplicate substitution paths trigger quality-gate dead-code flags and invite drift.
