---
id: 1449
topic: gotchas
source_issue: 11335
source_phase: plan
created_at: 2026-08-16T10:56:33.810887+00:00
status: active
corroborations: 1
---

# Regression-pin docstrings must avoid divergence escape-hatch words

Rule: when editing a `FakeIssueFetcher` docstring near a regression pin (e.g., `tests/regressions/test_issue_11335.py`), keep it free of the issue number plus any divergence-acceptance language.

- The pin's `_divergence_is_documented()` goes true on `"11335"` + a divergence word in the docstring.
- A docstring describing actual behaviour (not asserting an accepted gap) keeps the escape hatch closed.

**Why:** the escape hatch exists to document known gaps, but it silently passes tests that should fail if the docstring accidentally trips the trigger.
