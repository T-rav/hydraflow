---
id: 0014
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:13:17.693302+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011
---

# Use `is None` / `is not None` for optional sentinels

Prefer identity checks (`is None`, `is not None`) over equality checks for optional objects, especially callables and stores.

Example: `if callback is None: return` — not `if callback == None`.

**Why:** Identity checks are O(1) and immune to overridden `__eq__`; equality checks against `None` can accidentally match falsy custom objects with a permissive `__eq__`.
