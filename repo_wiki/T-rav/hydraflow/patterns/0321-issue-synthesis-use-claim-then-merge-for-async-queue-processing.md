---
id: 0321
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:37:54.874112+00:00
status: superseded
corroborations: 1
supersedes: 0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294,0295,0296,0297,0298,0299,0300,0301
superseded_by: 0344
---

# Use claim-then-merge for async queue processing

Atomically claim queue items (clear/load under lock), release lock, perform async work, re-acquire lock, reload new items, merge, then atomically write.

Example: `with lock: batch = queue.copy(); queue.clear()` → async work → `with lock: queue.update(new); queue.update(results); write(queue)`.

**Why:** Releasing the lock during async work avoids deadlock, but re-acquiring before write prevents entries appended during the async gap from being lost.
