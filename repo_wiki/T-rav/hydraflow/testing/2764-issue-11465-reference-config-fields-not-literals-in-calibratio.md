---
id: 2764
topic: testing
source_issue: 11465
source_phase: plan
created_at: 2026-08-20T06:26:27.906007+00:00
status: active
corroborations: 1
---

# Reference config fields, not literals, in calibration tests

Rule: In `tests/test_detector_calibration_loop.py`, assert against `loop._config.detector_calibration_spray_min_entities` rather than hardcoding `5`.

The threshold lives at `src/config.py:5371` and is tunable via env/config — tests using the literal silently break or false-pass when the default changes.

**Why:** Hardcoded literals in test assertions decouple the pin from the actual threshold the production code reads, creating false confidence after config changes.
