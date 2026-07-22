---
id: 0368
topic: gotchas
source_issue: 10299
source_phase: plan
created_at: 2026-07-22T17:49:09.980183+00:00
status: active
corroborations: 1
---

# Re-derive execution state on EpicManager.get_detail cache hits, not just on write

`EpicManager.get_detail` (src/epic.py) uses a 60s detail cache. If derived fields like `execution` are only computed at cache-write time, a worker pickup or queue drain that happens inside that 60s window won't be reflected until the cache expires. The fix for issue #10299 is to re-derive `execution` even on a cache hit, using the live worker-held/queued accessors.

**Why:** caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
