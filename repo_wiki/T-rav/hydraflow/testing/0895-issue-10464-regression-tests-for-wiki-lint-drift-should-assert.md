---
id: 0895
topic: testing
source_issue: 10464
source_phase: plan
created_at: 2026-07-24T15:39:21.687953+00:00
status: superseded
corroborations: 2
superseded_by: 0898
---

# Regression tests for wiki-lint drift should assert the full live-wiki lint, not one term

For drift regressions like #10464, write `tests/regressions/test_issue_10464.py` to assert `lint_paraphrases(TermStore(terms).list(), docs/wiki) == []` across the entire live wiki, not just the one flagged term file. This mirrors and reinforces `tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki`, and surfaces any other latent paraphrase drift already present on the branch before merge. **Why:** a narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
