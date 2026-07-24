---
id: 0513
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T09:05:16.784686+00:00
status: superseded
corroborations: 1
supersedes: 0446,0447,0448,0449,0450,0451,0452,0453,0454,0455,0456,0457,0458,0459,0460,0461,0462,0463,0464,0465,0466,0467,0468,0469,0470,0471,0472,0473,0474,0475,0476,0477,0478,0479,0480,0481,0482,0483,0484,0485,0486,0487,0488,0489,0492,0493
superseded_by: 0545
---

# Re-derive execution state on EpicManager cache hits, not just on write

Re-derive derived/live-state fields (like `execution`) even on a cache hit, not just at cache-write time.

Example: `EpicManager.get_detail` (src/epic.py) uses a 60s detail cache; the fix for issue #10299 re-derives `execution` on every call using live worker-held/queued accessors, so a worker pickup or queue drain inside the 60s window is reflected immediately.

**Why:** Caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
