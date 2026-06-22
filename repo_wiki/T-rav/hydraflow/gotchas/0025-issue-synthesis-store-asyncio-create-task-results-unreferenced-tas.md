---
id: 0025
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.695381+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Store `asyncio.create_task()` results — unreferenced tasks are GC'd silently

Assign every `asyncio.create_task()` result to a set and add a done callback for error logging.

Example: `self._tasks.add(t := asyncio.create_task(work())); t.add_done_callback(self._tasks.discard)`.

**Why:** Tasks without a live reference are garbage-collected mid-execution, silently dropping their work and exceptions with no observable signal.
