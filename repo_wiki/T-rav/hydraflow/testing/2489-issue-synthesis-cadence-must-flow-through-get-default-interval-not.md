---
id: 2489
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:50.321883+00:00
status: active
corroborations: 1
supersedes: 2299
---

# Cadence must flow through _get_default_interval(), not timers

Loop cadence is observed by tests through the base `run()` injected `sleep_fn`. Implementing a sub-schedule with raw `asyncio.sleep` or an internal timer leaves regression tests RED even when the code works.

Example: `HealthMonitorLoop._get_default_interval()` is the single source for the poll sleep; `tests/regressions/test_issue_10652.py` asserts cadence via the injected `sleep_fn` call sequence.

**Why:** Tests cannot see non-`sleep_fn` waits, so cadence changes are invisible to the acceptance oracle.
