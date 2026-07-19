---
id: 0347
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.495084+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Assert relative event ordering, not absolute IDs

Tests must never assert on absolute event counter values — only on relative ordering and uniqueness within a single test run.

Example: Good: `assert event_a.id < event_b.id`. Bad: `assert event_a.id == 1`.

**Why:** Global counters are shared across all test instances; absolute ID assertions are order-dependent and flaky under parallel execution.
