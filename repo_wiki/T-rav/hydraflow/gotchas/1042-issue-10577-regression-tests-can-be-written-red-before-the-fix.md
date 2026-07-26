---
id: 1042
topic: gotchas
source_issue: 10577
source_phase: plan
created_at: 2026-07-26T01:40:01.589371+00:00
status: active
corroborations: 1
---

# Regression tests can be written red before the fixing plan exists

`tests/regressions/test_issue_10577.py` was created and left failing (red) ahead of the implementation plan, and the plan explicitly names it as the acceptance bar: the fix must make it pass with zero edits to that file. When picking up a HydraFlow issue, check `tests/regressions/test_issue_<N>.py` first — if present, it may already encode the exact contract (e.g. "per-reason issue number must be attributable") the implementation is required to satisfy.

**Why:** treating the pre-existing regression test as an unmodifiable spec prevents scope drift during implementation.
