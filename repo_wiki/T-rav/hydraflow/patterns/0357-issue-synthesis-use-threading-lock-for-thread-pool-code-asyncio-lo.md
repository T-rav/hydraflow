---
id: 0357
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T18:01:25.881327+00:00
status: superseded
corroborations: 1
supersedes: 0350,0350,0351,0352,0353,0354,0355
superseded_by: 0364
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines only

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
