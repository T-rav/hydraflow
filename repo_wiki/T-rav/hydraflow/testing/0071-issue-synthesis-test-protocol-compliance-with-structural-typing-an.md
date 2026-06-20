---
id: 0071
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-06-14T14:41:04.271742+00:00
status: superseded
corroborations: 1
supersedes: 0034,0035,0036,0037,0038,0039,0040,0041,0042,0043,0044,0045,0046,0047,0048,0049,0050,0051,0052,0053,0054,0055,0056,0057,0058,0059,0060,0061,0062
superseded_by: 0093
---

# Test protocol compliance with structural typing and duck-typing

Verify protocol satisfaction with two complementary checks: (1) `isinstance(obj, Protocol)` with `@runtime_checkable`, and (2) `hasattr(obj, 'method_name')`. Add `inspect.signature()` comparison to detect parameter drift. Parametrize over each protocol method so failures are specific.

**Why:** Either check alone misses a class of violations; structural typing catches missing methods, signature comparison catches arity and keyword drift.
