---
id: 0014
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-13T05:43:53.409122+00:00
status: active
corroborations: 1
supersedes: 0001,0002,0003,0004,0005,0006
---

# Test protocol satisfaction with both isinstance and hasattr

Use two complementary checks: `isinstance(obj, Protocol)` with `@runtime_checkable`, and `hasattr(obj, 'method_name')` for each protocol method. Parametrize tests over all protocol methods.

Use `inspect.signature()` comparison to catch parameter drift between the protocol definition and the concrete implementation.

**Why:** `isinstance` alone misses methods added at runtime; `hasattr` alone skips type-contract enforcement.
