---
id: 0059
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T06:16:33.336338+00:00
status: active
corroborations: 1
supersedes: 0012,0012,0013,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043
---

# Store `asyncio.create_task()` results — unreferenced tasks are GC'd

Assign every `asyncio.create_task()` result to a set and add a done callback for error logging.

Example: `self._tasks.add(t := asyncio.create_task(work())); t.add_done_callback(self._tasks.discard)`.

**Why:** Tasks without a live reference are garbage-collected mid-execution, silently dropping their work and exceptions with no observable signal.
