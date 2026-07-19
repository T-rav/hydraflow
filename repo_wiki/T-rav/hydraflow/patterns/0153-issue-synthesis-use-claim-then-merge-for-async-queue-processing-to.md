---
id: 0153
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.026456+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# Use claim-then-merge for async queue processing to prevent lost entries

Atomically claim queue items (clear/load under lock), release lock, perform async work, re-acquire lock, reload new items, merge, then atomically write.

Example: `with lock: batch = queue.copy(); queue.clear()` → async work → `with lock: queue.update(new); queue.update(results); write(queue)`.

**Why:** Releasing the lock during async work is needed to avoid deadlock, but re-acquiring before write prevents entries appended during the async gap from being lost.
