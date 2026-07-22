---
id: 0345
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T04:08:36.286839+00:00
status: active
corroborations: 1
supersedes: 0302,0303,0304,0305,0306,0307,0308,0309,0310,0311,0312,0313,0314,0315,0316,0317,0318,0319,0320,0321,0322,0323,0324,0325,0326,0327,0328,0329,0330,0331,0332,0333,0334,0335,0336,0337,0338,0339,0340,0341,0342,0343
---

# Use `threading.Lock` for thread-pool code; `asyncio.Lock` for coroutines

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Use `asyncio.Lock` only for coordinating pure coroutines.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state. See also: ADR-0001 — five concurrent async loops.
