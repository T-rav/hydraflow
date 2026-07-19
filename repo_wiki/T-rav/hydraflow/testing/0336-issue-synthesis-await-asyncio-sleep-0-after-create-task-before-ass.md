---
id: 0336
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:25:25.488995+00:00
status: active
corroborations: 1
supersedes: 0295,0296,0297,0298,0299,0300,0301,0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333
---

# Await asyncio.sleep(0) after create_task() before asserting

After triggering a fire-and-forget task, yield one event loop tick before asserting.

Example: `task = asyncio.create_task(fn()); await asyncio.sleep(0); mock.assert_called_once()`

**Why:** Without yielding, the scheduled task has not run yet; assertions fire on stale state and produce false negatives.
