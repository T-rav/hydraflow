---
id: 0379
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-19T01:49:52.723682+00:00
status: active
corroborations: 1
supersedes: 0334,0335,0336,0337,0338,0339,0340,0341,0342,0343,0344,0345,0346,0347,0348,0349,0350,0351,0352,0353,0354,0355,0356,0357,0358,0359,0360,0361,0362,0363,0364,0365,0366,0367,0368,0369,0370,0371,0372
---

# Test protocols with isinstance and hasattr

Use two complementary checks: `isinstance(obj, Protocol)` with `@runtime_checkable`, and `hasattr(obj, 'method_name')` for each protocol method.

Example: Add `inspect.signature()` comparison to catch parameter drift. Parametrize tests over all protocol methods so failures are specific.

**Why:** `isinstance` alone misses methods added at runtime; `hasattr` alone skips type-contract enforcement.
