---
id: 0417
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.292393+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Concurrent planner pools must share max_planners semaphore, including gap review

When making epic-group planning and standalone planning run concurrently (e.g. via `asyncio.gather` in `plan_issues`, `src/plan_phase.py`), every code path that consumes a planner slot — including epic gap review — must acquire the same `max_planners` semaphore.

Example: gap review wasn't semaphore-guarded before this change; running it alongside the standalone pool without adding that guard oversubscribes past `max_planners`.

**Why:** Concurrency without a shared bound turns a capacity limit into a race condition that only shows up under load.
