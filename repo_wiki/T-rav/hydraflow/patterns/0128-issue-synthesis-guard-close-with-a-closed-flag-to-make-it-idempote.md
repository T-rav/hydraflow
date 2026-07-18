---
id: 0128
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T18:31:58.108416+00:00
status: active
corroborations: 1
supersedes: 0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062,0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091
---

# Guard `close()` with a `_closed` flag to make it idempotent

All cleanup methods must check and set a `_closed` flag as their first step.

Example: `def close(self): if self._closed: return; self._closed = True; await self._resource.aclose()`.

**Why:** Double-close on an async resource (e.g., HTTP session) raises; idempotent close makes teardown order-independent in test fixtures.
