---
id: 0108
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:07:53.467841+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Extract `_unlocked()` helpers to prevent re-entrant lock attempts

When a lock-holding method needs to call another method that also acquires the same lock, extract an `_unlocked()` variant and call that from both.

Example: `def update(self): with self._lock: self._update_unlocked()` — `batch_update` calls `_update_unlocked()` too.

**Why:** Re-entrant `threading.Lock` acquisition deadlocks; re-entrant `asyncio.Lock` raises — `_unlocked()` variants eliminate both failure modes.
