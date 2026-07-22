---
id: 0252
topic: gotchas
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-22T02:39:19.016774+00:00
status: active
corroborations: 1
supersedes: 0214,0215,0216,0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247
---

# Use `is None` / `is not None` for optional sentinels

Prefer identity checks (`is None`, `is not None`) over equality checks for optional objects, especially callables and stores.

Example: `if callback is None: return` — not `if callback == None`.

**Why:** Identity checks are O(1) and immune to overridden `__eq__`; equality checks against `None` can accidentally match falsy custom objects with a permissive `__eq__`.
