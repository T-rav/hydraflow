---
id: 0262
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T19:12:03.091762+00:00
status: active
corroborations: 1
supersedes: 0217,0218,0219,0220,0221,0222,0223,0224,0225,0226,0227,0228,0229,0230,0231,0232,0233,0234,0235,0236,0237,0238,0239,0240,0241,0242,0243,0244,0245,0246,0247,0248,0249,0250,0251,0252,0253,0254,0255
---

# Test protocol satisfaction with isinstance and hasattr

Use two complementary checks: `isinstance(obj, Protocol)` with `@runtime_checkable`, and `hasattr(obj, 'method_name')` for each protocol method.

Add `inspect.signature()` comparison to catch parameter drift. Parametrize tests over all protocol methods so failures are specific.

**Why:** `isinstance` alone misses methods added at runtime; `hasattr` alone skips type-contract enforcement.
