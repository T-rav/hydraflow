---
id: 0782
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T22:06:52.523293+00:00
status: active
corroborations: 1
supersedes: 0704,0705,0706,0707,0708,0709,0710,0711,0712,0713,0714,0715,0716,0717,0718,0719,0720,0721,0722,0723,0724,0725,0726,0727,0728,0729,0730,0731,0732,0733,0734,0735,0736,0737,0738,0739,0740,0741,0742,0743,0744,0745,0746,0747,0748,0749,0750,0751,0752,0753,0754,0755,0756,0757,0758,0759,0760,0761,0762
---

# Re-derive execution state on EpicManager cache hits, not just on write

Re-derive derived/live-state fields (like `execution`) even on a cache hit, not just at cache-write time.

Example: `EpicManager.get_detail` (src/epic.py) uses a 60s detail cache; the fix for issue #10299 re-derives `execution` on every call using live worker-held/queued accessors, so a worker pickup or queue drain inside the 60s window is reflected immediately.

**Why:** Caching for performance is fine, but caching a derived-from-live-state field silently freezes it, defeating the purpose of a real-time execution badge.
