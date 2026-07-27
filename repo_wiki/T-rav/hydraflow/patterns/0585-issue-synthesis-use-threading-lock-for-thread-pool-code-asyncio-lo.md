---
id: 0585
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-27T18:31:18.151319+00:00
status: active
corroborations: 1
supersedes: 0551
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines only

Use `threading.Lock` (not `asyncio.Lock`) for state shared with code running via `asyncio.to_thread()` or called from both sync and async contexts; reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
