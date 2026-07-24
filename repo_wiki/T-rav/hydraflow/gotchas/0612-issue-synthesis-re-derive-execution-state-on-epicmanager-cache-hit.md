---
id: 0612
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T12:09:28.232205+00:00
status: superseded
corroborations: 1
supersedes: 0545,0546,0547,0548,0549,0550,0551,0552,0553,0554,0555,0556,0557,0558,0559,0560,0561,0562,0563,0564,0565,0566,0567,0568,0569,0570,0571,0572,0573,0574,0575,0576,0577,0578,0579,0580,0581,0582,0583,0584,0585,0586,0587,0588,0589,0590,0591,0592
superseded_by: 0643
---

# Re-derive execution state on EpicManager cache hits, not just on write

Re-derive derived/live-state fields (like `execution`) even on a cache hit, not just at cache-write time.

Example: `EpicManager.get_detail` (src/epic.py) uses a 60s detail cache; the fix for issue #10299 re-derives `execution` on every call using live worker-held/queued accessors, so a worker pickup or queue drain inside the 60s window is reflected immediately.

**Why:** Caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
