---
id: 0363
topic: gotchas
source_issue: 10296
source_phase: plan
created_at: 2026-07-22T17:44:18.122239+00:00
status: active
corroborations: 1
---

# Concurrent planner pools must share max_planners semaphore, including gap review

When making epic-group planning and standalone planning run concurrently (e.g. via `asyncio.gather` in `plan_issues`, `src/plan_phase.py`), every code path that consumes a planner slot — including epic gap review — must acquire the same `max_planners` semaphore.

Gap review wasn't semaphore-guarded before this change; running it alongside the standalone pool without adding that guard oversubscribes past `max_planners`.

**Why:** concurrency without a shared bound turns a capacity limit into a race condition that only shows up under load.
