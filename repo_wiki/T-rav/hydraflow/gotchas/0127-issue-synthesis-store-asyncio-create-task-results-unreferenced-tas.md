---
id: 0127
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:37:07.467188+00:00
status: active
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
---

# Store `asyncio.create_task()` results — unreferenced tasks are GC'd

Assign every `asyncio.create_task()` result to a set and add a done callback for error logging.

Example: `self._tasks.add(t := asyncio.create_task(work())); t.add_done_callback(self._tasks.discard)`.

**Why:** Tasks without a live reference are garbage-collected mid-execution, silently dropping their work and exceptions with no observable signal.
