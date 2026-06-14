---
id: 0024
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.316066+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Extract `_unlocked()` helpers to prevent re-entrant lock attempts

When a lock-holding method needs to call another method that also acquires the same lock, extract an `_unlocked()` variant and call that from both.

Example: `def update(self): with self._lock: self._update_unlocked()` — `batch_update` calls `_update_unlocked()` too.

**Why:** Re-entrant `threading.Lock` acquisition deadlocks; re-entrant `asyncio.Lock` raises — `_unlocked()` variants eliminate both failure modes.
