---
id: 0301
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-18T20:38:53.879711+00:00
status: active
corroborations: 1
supersedes: 0256,0257,0258,0259,0260,0261,0262,0263,0264,0265,0266,0267,0268,0269,0270,0271,0272,0273,0274,0275,0276,0277,0278,0279,0280,0281,0282,0283,0284,0285,0286,0287,0288,0289,0290,0291,0292,0293,0294
---

# Test protocol satisfaction with isinstance and hasattr

Use two complementary checks: `isinstance(obj, Protocol)` with `@runtime_checkable`, and `hasattr(obj, 'method_name')` for each protocol method.

- Add `inspect.signature()` comparison to catch parameter drift.
- Parametrize tests over all protocol methods so failures are specific.

**Why:** `isinstance` alone misses methods added at runtime; `hasattr` alone skips type-contract enforcement.
