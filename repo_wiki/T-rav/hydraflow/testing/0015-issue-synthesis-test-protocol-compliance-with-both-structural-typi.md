---
id: 0015
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T05:17:49.828576+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Test protocol compliance with both structural typing and duck-typing

Verify protocol satisfaction with two complementary checks: (1) `isinstance(obj, Protocol)` with `@runtime_checkable`, and (2) `hasattr(obj, 'method_name')`. Add `inspect.signature()` comparison to detect parameter drift.

Parametrize over each protocol method so failures are specific.

**Why:** Either check alone misses a class of violations; structural typing catches missing methods, signature comparison catches arity and keyword drift.
