---
id: 0086
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T14:57:29.445727+00:00
status: active
corroborations: 1
supersedes: 0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033,0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049
---

# Guard `close()` with a `_closed` flag to make it idempotent

All cleanup methods must check and set a `_closed` flag as their first step.

Example: `def close(self): if self._closed: return; self._closed = True; await self._resource.aclose()`.

**Why:** Double-close on an async resource (e.g., HTTP session) raises; idempotent close makes teardown order-independent in test fixtures.
