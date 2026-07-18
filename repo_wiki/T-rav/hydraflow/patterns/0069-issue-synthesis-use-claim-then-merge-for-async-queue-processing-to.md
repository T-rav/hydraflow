---
id: 0069
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.436086+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Use claim-then-merge for async queue processing to prevent lost entries

Atomically claim queue items (clear/load under lock), release lock, perform async work, re-acquire lock, reload new items, merge, then atomically write.

Example: `with lock: batch = queue.copy(); queue.clear()` → async work → `with lock: queue.update(new); queue.update(results); write(queue)`.

**Why:** Releasing the lock during async work avoids deadlock, but re-acquiring before write prevents entries appended during the async gap from being lost.
