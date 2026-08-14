---
id: 2284
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-07-31T18:40:36.925866+00:00
status: superseded
corroborations: 1
supersedes: 2139
superseded_by: 2474
---

# Convert reviewer call sites to keyword args when changing arity

When removing a middle parameter from `ADRCouncilReviewer.__init__` (e.g. `pr_manager`), convert every call site to keyword arguments rather than just deleting the argument.

Example: call sites in `src/service_registry.py`, `tests/test_adr_reviewer.py`'s `_make_reviewer` helper, `tests/evals/test_adr_review_evals.py`, `tests/regressions/regression_issue_6732.py`.

**Why:** Positional call sites would silently rebind runner/credentials to the wrong slot after arity changes, producing a latent bug that unit tests may not catch.
