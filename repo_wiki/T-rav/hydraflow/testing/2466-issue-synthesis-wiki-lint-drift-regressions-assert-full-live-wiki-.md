---
id: 2466
topic: testing
source_issue: synthesis
source_phase: synthesis
created_at: 2026-08-14T20:25:49.953142+00:00
status: active
corroborations: 1
supersedes: 2276
---

# Wiki-lint drift regressions assert full live-wiki lint

For drift regressions, write `tests/regressions/*.py` to assert `lint_paraphrases(TermStore(terms).list(), docs/wiki) == []` across the entire live wiki, not just the one flagged term file.

Example: mirrors and reinforces `tests/test_seed_terms.py::test_paraphrase_lint_runs_against_live_wiki`.

**Why:** A narrowly-scoped regression test would pass while leaving other undetected alias collisions to break CI on a later PR.
