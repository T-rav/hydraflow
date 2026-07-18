---
id: 0066
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T04:09:01.907634+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Extract `_unlocked()` helpers to prevent re-entrant lock attempts

When a lock-holding method needs to call another method that also acquires the same lock, extract an `_unlocked()` variant and call that from both.

Example: `def update(self): with self._lock: self._update_unlocked()` — `batch_update` calls `_update_unlocked()` too.

**Why:** Re-entrant `threading.Lock` acquisition deadlocks; re-entrant `asyncio.Lock` raises — `_unlocked()` variants eliminate both failure modes.
