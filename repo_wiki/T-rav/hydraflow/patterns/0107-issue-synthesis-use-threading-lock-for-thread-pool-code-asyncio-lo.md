---
id: 0107
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T17:45:43.961522+00:00
status: superseded
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
superseded_by: 0134
---

# Use `threading.Lock` for thread-pool code; `asyncio.Lock` only for pure coroutines

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Use `asyncio.Lock` only for coordinating pure coroutines without thread-pool involvement.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
