---
id: 1223
topic: testing
source_issue: 10652
source_phase: plan
created_at: 2026-07-26T16:08:03.465289+00:00
status: superseded
corroborations: 1
superseded_by: 1297
---

# Cadence must flow through _get_default_interval(), not internal timers

Loop cadence is observed by tests through the base `run()` injected `sleep_fn`. Implementing a sub-schedule with raw `asyncio.sleep` or an internal timer leaves regression tests RED even when the code works.

- `HealthMonitorLoop._get_default_interval()` is the single source for the poll sleep
- `tests/regressions/test_issue_10652.py` asserts cadence via the injected `sleep_fn` call sequence

**Why:** Tests cannot see non-`sleep_fn` waits, so cadence changes are invisible to the acceptance oracle.
