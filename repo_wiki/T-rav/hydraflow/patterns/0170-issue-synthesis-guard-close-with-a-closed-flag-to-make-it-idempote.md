---
id: 0170
topic: patterns
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:52:49.031688+00:00
status: superseded
corroborations: 1
supersedes: 0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111,0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133
superseded_by: 0176
---

# Guard `close()` with a `_closed` flag to make it idempotent

All cleanup methods must check and set a `_closed` flag as their first step.

Example: `def close(self): if self._closed: return; self._closed = True; await self._resource.aclose()`.

**Why:** Double-close on an async resource (e.g., HTTP session) raises; idempotent close makes teardown order-independent in test fixtures.
