---
id: 0023
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.410246+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Assert relative event ordering, not absolute ID values

Tests must never assert on absolute event counter values — only on relative ordering and uniqueness within a single test run.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global counters are shared across all test instances; absolute ID assertions are order-dependent and flaky under parallel execution.
