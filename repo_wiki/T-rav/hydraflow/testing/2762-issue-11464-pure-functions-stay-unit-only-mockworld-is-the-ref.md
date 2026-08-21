---
id: 2762
topic: testing
source_issue: 11464
source_phase: plan
created_at: 2026-08-20T06:25:26.202144+00:00
status: active
corroborations: 1
---

# Pure functions stay unit-only; MockWorld is the refactor tripwire

Keep pure functions like `_template_key` at the enforced unit-only layer — no Port, loop, orchestrator, or subprocess touched. New tests live in `tests/test_detector_calibration_loop.py`; `tests/scenarios/test_detector_calibration_scenario.py` (MockWorld) and `tests/regressions/test_issue_11405.py` serve as behavior-preservation tripwires when you refactor `template_key`.

**Why:** `docs/standards/testing/README.md` enforces the pyramid; crossing layers triggers ADR-0049 kill-switch review.
