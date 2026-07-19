---
id: 0191
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:22:06.633355+00:00
status: active
corroborations: 1
supersedes: 0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145,0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175
---

# Use `threading.Lock` for thread-pool code; `asyncio.Lock` only for pure coroutines

When code runs via `asyncio.to_thread()` or is called from both sync and async contexts, use `threading.Lock`. Use `asyncio.Lock` only for coordinating pure coroutines without thread-pool involvement.

Example: `self._lock = threading.Lock()` for a cache shared between thread-pool workers.

**Why:** `asyncio.Lock` is not thread-safe — acquiring it from a thread pool raises or silently corrupts state.
