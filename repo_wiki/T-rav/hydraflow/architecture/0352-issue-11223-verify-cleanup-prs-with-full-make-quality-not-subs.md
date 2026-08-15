---
id: 0352
topic: architecture
source_issue: 11223
source_phase: plan
created_at: 2026-08-15T06:46:05.624548+00:00
status: active
corroborations: 1
---

# Verify cleanup PRs with full make quality, not subsets

Per CLAUDE.md, cleanup PRs in T-rav/hydraflow must pass full `make quality` — do not verify with file-targeted test subsets (see PR #8460/#8463). Alongside `tests/test_review_phase_core.py`, run `tests/test_state_tracking.py`, `tests/test_state_counters.py`, `tests/test_state_mixin_decomposition.py`, and `tests/test_state_int_key_helpers.py` to prove retained accessors are untouched.

**Why:** File-targeted subsets miss cross-module dead-code references and lint regressions that the full quality gate catches.
