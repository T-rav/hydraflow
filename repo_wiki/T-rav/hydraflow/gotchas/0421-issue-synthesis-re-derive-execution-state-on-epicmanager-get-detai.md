---
id: 0421
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:55:43.294842+00:00
status: active
corroborations: 1
supersedes: 0370,0371,0372,0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387,0388,0389,0390,0391,0392,0393,0394,0395,0396,0397,0398,0399,0400,0401
---

# Re-derive execution state on EpicManager.get_detail cache hits, not just on write

Re-derive derived/live-state fields (like `execution`) even on a cache hit, not just at cache-write time.

Example: `EpicManager.get_detail` (src/epic.py) uses a 60s detail cache; the fix for issue #10299 re-derives `execution` on every call using live worker-held/queued accessors, so a worker pickup or queue drain inside the 60s window is reflected immediately.

**Why:** Caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
