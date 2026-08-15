---
id: 1363
topic: gotchas
source_issue: 11193
source_phase: plan
created_at: 2026-08-15T00:39:44.183381+00:00
status: active
corroborations: 1
---

# Self-retire regression pins when target ADRs are absent

Resolve ADR lookups in `tests/regressions/` with a default and self-retire (skip/early-return) when the target ADR is absent.

- Avoid: `next(a for a in adrs if a.number == 13)`
- Use: `next((a for a in adrs if a.number == 13), None)` followed by an early return if `None`.
- Reference shape: `tests/regressions/test_issue_9176.py:77`.

**Why:** Bare `next(...)` raises `StopIteration` if the ADR is removed or renumbered, turning a silent trap into a build failure.
