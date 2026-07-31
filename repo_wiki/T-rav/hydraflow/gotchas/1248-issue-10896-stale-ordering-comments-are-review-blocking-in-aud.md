---
id: 1248
topic: gotchas
source_issue: 10896
source_phase: plan
created_at: 2026-07-31T12:32:01.782714+00:00
status: active
corroborations: 1
---

# Stale ordering comments are review-blocking in audit sampling modules

When reordering logic in `src/audit/sampling.py`, update every docstring/comment asserting the old ordering. Three locations said "excluded before classification, never classified" and all required amending: the `select_sample` inline comment, `is_self_chore_change`'s docstring, and `tests/regressions/regression_issue_10808.py`'s docstring.

**Why:** Comments are the contract for invariants — false comments mislead future maintainers into reverting correct logic or introducing the exact bug being fixed.
