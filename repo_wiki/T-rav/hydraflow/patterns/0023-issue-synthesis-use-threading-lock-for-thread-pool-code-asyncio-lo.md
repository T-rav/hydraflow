---
id: 0023
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.315867+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Use `threading.Lock` for thread-pool code; `asyncio.Lock` only for pure coroutines

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Use `asyncio.Lock` only for coordinating pure coroutines without thread-pool involvement.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
