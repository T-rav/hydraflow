---
id: 2763
topic: testing
source_issue: 11465
source_phase: plan
created_at: 2026-08-20T06:26:27.905979+00:00
status: active
corroborations: 1
---

# Mutation-kill new test pins before shipping green

Rule: Temporarily break the production code path a new test claims to guard, rerun, confirm the test FAILs, then revert and ship green.

Example: change `>=` to `>` on `src/detector_calibration_loop.py:227` or empty the `spraying` comprehension → new spray tests must FAIL before reverting.

**Why:** Green-on-arrival tests that don't fail when the guarded code is broken are coverage-gap theater, not regression pins.
