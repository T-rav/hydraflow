---
id: 0279
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.715196+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Use claim-then-merge for async queue processing

Atomically claim queue items (clear/load under lock), release lock, perform async work, re-acquire lock, reload new items, merge, then atomically write.

Example: `with lock: batch = queue.copy(); queue.clear()` → async work → `with lock: queue.update(new); queue.update(results); write(queue)`.

**Why:** Releasing the lock during async work avoids deadlock, but re-acquiring before write prevents entries appended during the async gap from being lost.
