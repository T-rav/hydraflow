---
id: 0365
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T04:10:17.162193+00:00
status: superseded
corroborations: 1
supersedes: 0356,0357,0358,0359,0360,0361,0362,0363
superseded_by: 0373
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines only

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
