---
id: 2750
topic: testing
source_issue: 11423
source_phase: plan
created_at: 2026-08-18T04:02:35.358227+00:00
status: stale
corroborations: 1
stale_reason: source issue #11423 closed
---

# _signatures_compatible ignores Parameter.kind (#11415 scope)

`tests.test_mockworld_fakes_conformance._signatures_compatible` does not check `Parameter.kind`, so it accepts a positional→keyword-only narrowing. This is a known hole tracked in #11415 — do not pull it into other issues.

- `tests/regressions/test_issue_11423.py` includes a context test that feeds synthetic signatures to `_signatures_compatible` and asserts it still accepts the narrowing, documenting the gap.

**Why:** Conflating #11415's scope with a kind-narrowing fix expands the change surface and risks regressions in the comparator's other callers; the hole is tracked separately and survives unrelated fixes unchanged.
