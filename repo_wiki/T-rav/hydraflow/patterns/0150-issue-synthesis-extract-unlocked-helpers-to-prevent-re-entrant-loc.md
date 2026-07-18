---
id: 0150
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.025586+00:00
status: active
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
---

# Extract `_unlocked()` helpers to prevent re-entrant lock attempts

When a lock-holding method needs to call another method that also acquires the same lock, extract an `_unlocked()` variant and call that from both.

Example: `def update(self): with self._lock: self._update_unlocked()` — `batch_update` calls `_update_unlocked()` too.

**Why:** Re-entrant `threading.Lock` acquisition deadlocks; re-entrant `asyncio.Lock` raises — `_unlocked()` variants eliminate both failure modes.
