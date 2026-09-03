---
id: 1569
topic: gotchas
source_issue: 12058
source_phase: plan
created_at: 2026-09-02T22:01:19.186910+00:00
status: active
corroborations: 1
---

# Return-type fanout in budget-return API change

`file_overflow_summary` now returns the issue number (or 0-sentinel for no-op), not a count. Callers in `src/gate_health_loop.py` and `src/detector_calibration_loop.py` must adapt via `1 if num else 0`, or stats corrupt silently.

Example: Replace `summary_count = file_overflow_summary(...)` with `summary_count = 1 if file_overflow_summary(...) else 0`.

**Why:** A missed adaptation reports issue numbers as filing counts, corrupting KPIs without error.
