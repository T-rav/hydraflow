---
id: 0898
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T02:33:17.843091+00:00
status: superseded
corroborations: 1
supersedes: 0840
superseded_by: 0962
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines

Use `threading.Lock` (not `asyncio.Lock`) for state shared with code running via `asyncio.to_thread()` or called from both sync and async contexts; reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
