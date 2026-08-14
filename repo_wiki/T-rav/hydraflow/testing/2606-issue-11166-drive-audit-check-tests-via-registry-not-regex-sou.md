---
id: 2606
topic: testing
source_issue: 11166
source_phase: plan
created_at: 2026-08-14T19:18:14.572505+00:00
status: active
corroborations: 1
---

# Drive audit check tests via registry, not regex source

Regression pins for p8 checks should call `registry.get("P8.7")` against a `tmp_path` CLAUDE.md, asserting behavior — never import or inspect the regex pattern directly.

Structure in `tests/regressions/test_issue_11166.py`: three FAIL cases (one per exposed branch/marker) plus three over-tightening counter-pins (paraphrase, inflection, live repo).

**Why:** Source-level tests survive refactors that preserve behavior but change internals; behavior tests catch the actual false-PASS failure mode.
