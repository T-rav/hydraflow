---
id: 0276
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T02:42:57.713975+00:00
status: active
corroborations: 1
supersedes: 0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255,0256,0257,0258,0259
---

# Extract `_unlocked()` helpers to prevent re-entrant lock attempts

When a lock-holding method needs to call another method that also acquires the same lock, extract an `_unlocked()` variant and call that from both.

Example: `def update(self): with self._lock: self._update_unlocked()` — `batch_update` calls `_update_unlocked()` too.

**Why:** Re-entrant `threading.Lock` acquisition deadlocks; re-entrant `asyncio.Lock` raises — `_unlocked()` variants eliminate both failure modes.
