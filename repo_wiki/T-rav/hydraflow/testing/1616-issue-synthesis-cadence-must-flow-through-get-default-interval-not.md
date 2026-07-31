---
id: 1616
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T01:04:04.436134+00:00
status: active
corroborations: 1
supersedes: 1534
---

# Cadence must flow through _get_default_interval(), not timers

Loop cadence is observed by tests through the base run() injected sleep_fn. Implementing a sub-schedule with raw asyncio.sleep or an internal timer leaves regression tests RED even when the code works.

Example: HealthMonitorLoop._get_default_interval() is the single source for the poll sleep; tests/regressions/test_issue_10652.py asserts cadence via the injected sleep_fn call sequence.

**Why:** Tests cannot see non-sleep_fn waits, so cadence changes are invisible to the acceptance oracle.
