---
id: 0389
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-24T07:23:13.604262+00:00
status: superseded
corroborations: 1
supersedes: 0373,0374,0375,0376,0377,0378,0379,0380,0381,0382,0383,0384,0385,0386,0387
superseded_by: 0402
---

# Use threading.Lock for thread-pool code; asyncio.Lock for coroutines only

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Reserve `asyncio.Lock` for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers. See also: ADR-0001 — five concurrent async loops.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
