---
id: 0403
topic: architecture
source_issue: 11423
source_phase: plan
created_at: 2026-08-18T04:02:35.358220+00:00
status: active
corroborations: 1
---

# tests/regressions/ may import private symbols from conformance tests

Regression tests under `tests/regressions/` may import underscore-prefixed symbols from `tests/test_mockworld_fakes_conformance.py` directly — do not add public aliases for these.

- Precedent: `tests/regressions/test_issue_11415.py` imports `_signatures_compatible`.
- `tests/regressions/test_issue_11423.py` follows the same pattern for `_PORT_FAKE_PAIRS`, `_named_params`, `_public_methods`.

**Why:** This is test→test import inside `tests/`; adding public aliases in conformance modules is unnecessary churn and breaks the established convention.
