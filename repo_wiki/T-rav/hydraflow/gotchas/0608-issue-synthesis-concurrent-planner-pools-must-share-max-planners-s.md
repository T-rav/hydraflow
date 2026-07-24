---
id: 0608
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.216736+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Concurrent planner pools must share max_planners semaphore, gap review too

When making epic-group planning and standalone planning run concurrently (e.g. via `asyncio.gather` in `plan_issues`, `src/plan_phase.py`), every code path that consumes a planner slot — including epic gap review — must acquire the same `max_planners` semaphore.

Example: gap review wasn't semaphore-guarded before this change; running it alongside the standalone pool without adding that guard oversubscribes past `max_planners`.

**Why:** Concurrency without a shared bound turns a capacity limit into a race condition that only shows up under load.
