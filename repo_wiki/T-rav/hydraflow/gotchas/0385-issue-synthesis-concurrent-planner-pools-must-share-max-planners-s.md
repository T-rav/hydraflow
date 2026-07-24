---
id: 0385
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:12:12.390739+00:00
status: superseded
corroborations: 1
supersedes: 0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369
superseded_by: 0402
---

# Concurrent planner pools must share max_planners semaphore, including gap review

When making epic-group planning and standalone planning run concurrently (e.g. via `asyncio.gather` in `plan_issues`, `src/plan_phase.py`), every code path that consumes a planner slot — including epic gap review — must acquire the same `max_planners` semaphore.

Example: gap review wasn't semaphore-guarded before this change; running it alongside the standalone pool without adding that guard oversubscribes past `max_planners`.

**Why:** Concurrency without a shared bound turns a capacity limit into a race condition that only shows up under load.
