---
id: 0263
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.027394+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Store `asyncio.create_task()` results — unreferenced tasks are GC'd

Assign every `asyncio.create_task()` result to a set and add a done callback for error logging.

Example: `self._tasks.add(t := asyncio.create_task(work())); t.add_done_callback(self._tasks.discard)`.

**Why:** Tasks without a live reference are garbage-collected mid-execution, silently dropping their work and exceptions with no observable signal.
