---
id: 0564
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T10:39:28.192341+00:00
status: superseded
corroborations: 1
supersedes: 0494,0495,0496,0497,0498,0499,0500,0501,0502,0503,0504,0505,0506,0507,0508,0509,0510,0511,0512,0513,0514,0515,0516,0517,0518,0519,0520,0521,0522,0523,0524,0525,0526,0527,0528,0529,0530,0531,0532,0533,0534,0535,0536,0537,0538,0539
superseded_by: 0593
---

# Re-derive execution state on EpicManager cache hits, not just on write

Re-derive derived/live-state fields (like `execution`) even on a cache hit, not just at cache-write time.

Example: `EpicManager.get_detail` (src/epic.py) uses a 60s detail cache; the fix for issue #10299 re-derives `execution` on every call using live worker-held/queued accessors, so a worker pickup or queue drain inside the 60s window is reflected immediately.

**Why:** Caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
