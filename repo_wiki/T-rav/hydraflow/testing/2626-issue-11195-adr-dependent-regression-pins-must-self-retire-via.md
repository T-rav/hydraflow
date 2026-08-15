---
id: 2626
topic: testing
source_issue: 11195
source_phase: plan
created_at: 2026-08-15T01:07:17.473951+00:00
status: active
corroborations: 1
---

# ADR-dependent regression pins must self-retire via next(..., None)

Regression tests that pin behavior to a specific ADR (e.g. `test_issue_10565.py` pinning ADR-0013) must use `next((...), None)` with `pytest.skip(...)` on absence, never a bare `next(a for a in adrs)`.

- Pattern: `adr = next((a for a in adrs if a.number == 13), None); if adr is None: pytest.skip(...)`
- Applies to the #11180/#11186/#11192/#11195 family of sibling fixes.

**Why:** Routine ADR renumbering or removal raises `StopIteration` in CI on unrelated PRs, breaking the pin instead of retiring it.
