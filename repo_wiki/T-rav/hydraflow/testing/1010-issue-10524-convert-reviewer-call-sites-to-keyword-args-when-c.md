---
id: 1010
topic: testing
source_issue: 10524
source_phase: plan
created_at: 2026-07-25T07:08:18.759692+00:00
status: active
corroborations: 1
---

# Convert reviewer call sites to keyword args when changing arity

When removing a middle parameter from `ADRCouncilReviewer.__init__` (e.g. `pr_manager`), convert every call site — `src/service_registry.py`, `tests/test_adr_reviewer.py`'s `_make_reviewer` helper, `tests/evals/test_adr_review_evals.py`, `tests/regressions/regression_issue_6732.py` — to keyword arguments rather than just deleting the argument.

**Why:** positional call sites would silently rebind `runner`/`credentials` to the wrong slot after arity changes, producing a latent bug that unit tests may not catch if mocks tolerate type mismatches.
