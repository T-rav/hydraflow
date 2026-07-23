---
id: 0184
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:47:09.151901+00:00
status: superseded
corroborations: 1
supersedes: 0146,0147,0148,0149,0150,0151,0152,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179
superseded_by: 0214
---

# Use `is None` / `is not None` for optional sentinels

Prefer identity checks (`is None`, `is not None`) over equality checks for optional objects, especially callables and stores.

Example: `if callback is None: return` — not `if callback == None`.

**Why:** Identity checks are O(1) and immune to overridden `__eq__`; equality checks against `None` can accidentally match falsy custom objects with a permissive `__eq__`.
