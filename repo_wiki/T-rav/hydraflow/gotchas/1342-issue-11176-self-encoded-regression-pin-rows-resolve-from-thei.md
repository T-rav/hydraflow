---
id: 1342
topic: gotchas
source_issue: 11176
source_phase: plan
created_at: 2026-08-14T22:35:54.596995+00:00
status: active
corroborations: 1
---

# Self-encoded regression-pin rows resolve from their own commit diff

Rule: An aged `regression-pin` escape whose detecting commit added a regression test in its own diff is machine-resolvable as `encoded_as=regression-test` without a human ask.

- Example: `regression-pin:055267e7b2b7` shipped `tests/regressions/test_issue_10440.py` in its diff; the ledger's `RESOLVED_ENCODED` predicate catches this via `encoded_as != "none-yet"`.
- The aging surface (`reason != SURFACE_REASON_LOW_CONFIDENCE`) was previously excluded from `_auto_diagnose`, so these rows never auto-resolved.

**Why:** Spending human-ask budget on self-evident encodings drains the budget from genuine escapes that actually need a human.
