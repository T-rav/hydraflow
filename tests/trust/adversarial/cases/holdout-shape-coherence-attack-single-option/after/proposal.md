# Shape Proposal: Speed up /api/summary

## Option A: Cache the summary aggregate

Compute the dashboard summary on a 30-second background refresh and serve
the cached aggregate from memory.

- Scope: `src/routes_summary.py`, `src/summary_cache.py` (new)
- Trade-off: header data can be up to 30 seconds stale, and the cache
  refresh adds a background task to supervise.

## Option B: Defer

Accept the status quo. Cost of inaction: the dashboard header stays at
roughly 1.8s p95 and operators keep filing latency complaints.
