---
id: 0150
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T00:23:52.948484+00:00
status: superseded
corroborations: 1
supersedes: 0112,0113,0114,0115,0116,0117,0118,0119,0120,0121,0122,0123,0124,0125,0126,0127,0128,0129,0130,0131,0132,0133,0134,0135,0136,0137,0138,0139,0140,0141,0142,0143,0144,0145
superseded_by: 0180
---

# Use `is None` / `is not None` for optional sentinels

Prefer identity checks (`is None`, `is not None`) over equality checks for optional objects, especially callables and stores.

Example: `if callback is None: return` — not `if callback == None`.

**Why:** Identity checks are O(1) and immune to overridden `__eq__`; equality checks against `None` can accidentally match falsy custom objects with a permissive `__eq__`.
