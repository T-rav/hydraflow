---
id: 0116
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T21:54:44.598263+00:00
status: superseded
corroborations: 1
supersedes: 0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092,0093,0094,0095,0096,0097,0098,0099,0100,0101,0102,0103,0104,0105,0106,0107,0108,0109,0110,0111
superseded_by: 0146
---

# Use `is None` / `is not None` for optional sentinels

Prefer identity checks (`is None`, `is not None`) over equality checks for optional objects, especially callables and stores.

Example: `if callback is None: return` — not `if callback == None`.

**Why:** Identity checks are O(1) and immune to overridden `__eq__`; equality checks against `None` can accidentally match falsy custom objects with a permissive `__eq__`.
