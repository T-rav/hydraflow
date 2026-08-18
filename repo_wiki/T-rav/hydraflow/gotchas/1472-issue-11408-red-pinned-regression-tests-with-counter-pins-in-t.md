---
id: 1472
topic: gotchas
source_issue: 11408
source_phase: plan
created_at: 2026-08-18T02:52:22.040875+00:00
status: active
corroborations: 1
---

# RED-pinned regression tests with counter-pins in tests/regressions/

Rule: Pre-write regression tests in `tests/regressions/test_issue_NNNNN.py` as RED before the fix; keep them unmodified as the enforced pin. Include counter-pins — assertions that stay green today and reject alternative non-fixes (e.g., deleting the `None` fallback, hardcoding literals unconditionally).

Example for #11408: 2 RED tests pin the bug (explicit-empty advisory retires nothing; both parameters agree on empty semantics); 5 green counter-pins reject fixes that remove the `None` fallback, hardcode literals, or break the existing empty-protected behaviour.

**Why:** Counter-pins prevent a "fix" that satisfies failing assertions by removing desired behaviour rather than correcting the bug.
