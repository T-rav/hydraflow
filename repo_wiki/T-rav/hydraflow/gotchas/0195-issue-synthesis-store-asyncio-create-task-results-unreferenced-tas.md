---
id: 0195
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.155653+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Store `asyncio.create_task()` results — unreferenced tasks are GC'd

Assign every `asyncio.create_task()` result to a set and add a done callback for error logging.

Example: `self._tasks.add(t := asyncio.create_task(work())); t.add_done_callback(self._tasks.discard)`.

**Why:** Tasks without a live reference are garbage-collected mid-execution, silently dropping their work and exceptions with no observable signal.
