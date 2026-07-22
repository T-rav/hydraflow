---
id: 0350
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T12:09:24.764389+00:00
status: active
corroborations: 1
supersedes: 0344,0345,0346,0347,0349
---

# Use `threading.Lock` for thread-pool code; `asyncio.Lock` for coroutines

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Use `asyncio.Lock` only for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state. See also: ADR-0001 — five concurrent async loops.
