---
id: 0308
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.883393+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Assert relative event ordering, not absolute ID values

Tests must never assert on absolute event counter values — only on relative ordering and uniqueness within a single test run.

- Good: `assert event_a.id < event_b.id`
- Bad: `assert event_a.id == 1`

**Why:** Global counters are shared across all test instances; absolute ID assertions are order-dependent and flaky under parallel execution.
