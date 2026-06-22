---
id: 0194
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-20T05:43:45.786664+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0153,0154,0155,0156,0157,0158,0159,0160,0161,0162,0163,0164,0165,0166,0167,0168,0169,0170,0171,0172,0173,0174,0175,0176,0177,0178,0179,0180,0181,0182
---

# Test protocol compliance with structural typing and duck-typing

Verify protocol satisfaction with two complementary checks: (1) `isinstance(obj, Protocol)` with `@runtime_checkable`, and (2) `hasattr(obj, 'method_name')`. Add `inspect.signature()` comparison to detect parameter drift. Parametrize over each protocol method so failures are specific.

**Why:** Either check alone misses a class of violations; structural typing catches missing methods, signature comparison catches arity and keyword drift.
