---
id: 0374
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T05:53:43.445508+00:00
status: superseded
corroborations: 1
supersedes: 0364,0365,0366,0367,0368,0369,0370,0371,0372
superseded_by: 0388
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines only

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
