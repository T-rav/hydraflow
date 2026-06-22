---
id: 0044
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:09:18.320497+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007
---

# Guard `close()` with a `_closed` flag to make it idempotent

All cleanup methods must check and set a `_closed` flag as their first step.

Example: `def close(self): if self._closed: return; self._closed = True; await self._resource.aclose()`.

**Why:** Double-close on an async resource (e.g., HTTP session) raises; idempotent close makes teardown order-independent in test fixtures.
