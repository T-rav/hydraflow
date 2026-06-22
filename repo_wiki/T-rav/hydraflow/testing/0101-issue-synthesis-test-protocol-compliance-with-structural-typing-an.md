---
id: 0101
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T15:18:41.081892+00:00
status: superseded
corroborations: 1
supersedes: 0063,0064,0065,0066,0067,0068,0069,0070,0071,0072,0073,0074,0075,0076,0077,0078,0079,0080,0081,0082,0083,0084,0085,0086,0087,0088,0089,0090,0091,0092
superseded_by: 0123
---

# Test protocol compliance with structural typing and duck-typing

Verify protocol satisfaction with two complementary checks: (1) `isinstance(obj, Protocol)` with `@runtime_checkable`, and (2) `hasattr(obj, 'method_name')`. Add `inspect.signature()` comparison to detect parameter drift. Parametrize over each protocol method so failures are specific.

**Why:** Either check alone misses a class of violations; structural typing catches missing methods, signature comparison catches arity and keyword drift.
