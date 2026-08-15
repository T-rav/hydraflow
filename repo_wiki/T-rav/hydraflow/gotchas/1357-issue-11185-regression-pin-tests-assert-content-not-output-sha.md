---
id: 1357
topic: gotchas
source_issue: 11185
source_phase: plan
created_at: 2026-08-14T23:55:43.383213+00:00
status: stale
corroborations: 1
stale_reason: source issue #11185 closed
---

# Regression pin tests assert content, not output shape

Regression pin tests (in `tests/regressions/`) should assert that expected *content* reaches the output, not the *structural shape* of the output.

- `test_issue_11185.py` asserts only that an artifact path appears in the markdown — no column-count or table-shape assertion.
- The issue accepts either a table column or a detail line, so a shape assertion would over-pin.

**Why:** Over-pinning shape blocks valid alternative implementations and turns future refactors into spurious failures.
