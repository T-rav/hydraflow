---
id: 0027
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.316653+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use claim-then-merge for async queue processing to prevent lost entries

Atomically claim queue items (clear/load under lock), release lock, perform async work, re-acquire lock, reload new items, merge, then atomically write.

Example: `with lock: batch = queue.copy(); queue.clear()` → async work → `with lock: queue.update(new); queue.update(results); write(queue)`.

**Why:** Releasing the lock during async work is needed to avoid deadlock, but re-acquiring before write prevents entries appended during the async gap from being lost.
