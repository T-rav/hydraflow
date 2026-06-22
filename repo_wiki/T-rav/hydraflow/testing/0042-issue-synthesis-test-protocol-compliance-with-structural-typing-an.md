---
id: 0042
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T10:20:54.211890+00:00
status: superseded
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006,0007,0008,0009,0010,0011,0012,0013,0014,0015,0016,0017,0018,0019,0020,0021,0022,0023,0024,0025,0026,0027,0028,0029,0030,0031,0032,0033
superseded_by: 0063
---

# Test protocol compliance with structural typing and duck-typing

Verify protocol satisfaction with two complementary checks: (1) `isinstance(obj, Protocol)` with `@runtime_checkable`, and (2) `hasattr(obj, 'method_name')`. Add `inspect.signature()` comparison to detect parameter drift. Parametrize over each protocol method so failures are specific.

**Why:** Either check alone misses a class of violations; structural typing catches missing methods, signature comparison catches arity and keyword drift.
